from http.server import BaseHTTPRequestHandler
import json
import requests
from bs4 import BeautifulSoup
import re
import base64
import io

# --- YARDIMCI VERI MODELLERI (Basit Dict Yapısı) ---

class OBSClient:
    # --- URL SABİTLERİ ---
    BASE_URL = "https://obs.ozal.edu.tr/oibs/std/"
    LOGIN_URL = "https://obs.ozal.edu.tr/oibs/std/login.aspx"
    GRADES_URL = "https://obs.ozal.edu.tr/oibs/std/not_listesi_op.aspx"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.LOGIN_URL,
            "Origin": "https://obs.ozal.edu.tr",
            "Cache-Control": "no-cache"
        })

    def set_cookies(self, cookie_dict):
        """Mobil uygulamadan gelen session cookie'lerini yükler."""
        if cookie_dict:
            requests.utils.add_dict_to_cookiejar(self.session.cookies, cookie_dict)

    def get_cookies(self):
        """Mevcut session cookie'lerini dict olarak döner."""
        return requests.utils.dict_from_cookiejar(self.session.cookies)

    def _get_hidden_inputs(self, soup: BeautifulSoup):
        """ASP.NET için gerekli ViewState vb. verileri toplar."""
        data = {}
        for inp in soup.find_all("input", type="hidden"):
            if inp.get("name"):
                data[inp.get("name")] = inp.get("value", "")
        return data

    def fetch_login_page(self):
        """
        Adım 1: Login sayfasını açar, Captcha'yı RAM'de base64 yapar.
        """
        r = self.session.get(self.LOGIN_URL)
        soup = BeautifulSoup(r.content, "html.parser")

        # 1. Captcha Bul
        captcha_b64 = None
        img_tag = soup.find(id="imgCaptchaImg")
        
        if img_tag:
            src = img_tag.get("src")
            # URL düzeltme mantığın (Senin çalışan kodundan)
            if not src.startswith("http"):
                url = self.BASE_URL + src.lstrip("/") if src.startswith("/") else self.BASE_URL + src
            else:
                url = src
            
            try:
                # Resmi İndir (Stream kullanmadan direkt content alalım, küçük resim zaten)
                r_img = self.session.get(url)
                
                if r_img.status_code == 200:
                    # Diske yazmak yerine direkt bellekte Base64'e çevir
                    captcha_b64 = base64.b64encode(r_img.content).decode('utf-8')
                else:
                    print(f"Resim indirilemedi: {r_img.status_code}") # Loglara düşsün

            except Exception as e:
                print(f"Captcha işleme hatası: {str(e)}")

        # 2. Hidden Inputları al
        hidden_inputs = self._get_hidden_inputs(soup)

        return {
            "captcha_image": captcha_b64,
            "view_state_data": hidden_inputs,
            "cookies": self.get_cookies()
        }

    def attempt_login(self, username, password, captcha_code, view_state_data):
        """
        Adım 2: Kullanıcıdan gelen bilgilerle POST isteği atar.
        """
        payload = view_state_data.copy()
        payload.update({
            "txtParamT01": username,
            "txtParamT02": password,
            "txtParamT1": password,
            "txtSecCode": captcha_code,
            "__EVENTTARGET": "btnLogin",
            "__EVENTARGUMENT": "",
            "txt_scrWidth": "1920", 
            "txt_scrHeight": "1080"
        })
        # btnLogin key'i bazen sorun çıkarır, silelim
        if "btnLogin" in payload: del payload["btnLogin"]

        # POST İsteği
        r_post = self.session.post(self.LOGIN_URL, data=payload)

        # Başarılı mı? (URL değiştiyse veya login form yoksa başarılıdır)
        is_success = "login.aspx" not in r_post.url
        
        return {
            "success": is_success,
            "cookies": self.get_cookies(), # Güncellenmiş cookie'leri (Auth Token) geri dön
            "message": "Giriş Başarılı" if is_success else "Giriş Başarısız. Captcha veya Şifre yanlış."
        }

    def fetch_grades_data(self):
        """Notları çeker."""
        # Session düştü mü kontrolü için header güncelle
        self.session.headers.update({"Referer": self.GRADES_URL})
        r = self.session.get(self.GRADES_URL)
        
        if "login.aspx" in r.url:
            return {"error": "Oturum süresi dolmuş, tekrar giriş yapın."}

        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find(id="grd_not_listesi")
        
        if not table:
            return {"courses": []}

        # Dönem Bilgisi
        donem_val = "20251" # Default fallback
        donem_select = soup.find("select", id="cmbDonemler")
        if donem_select:
            opt = donem_select.find("option", selected=True)
            if opt: donem_val = opt.get("value")

        grades_list = []
        rows = table.find_all("tr")[1:] # Header'ı atla

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 5: continue

            # --- AJAX Istatistikleri İçin Hazırlık ---
            # Not: Serverless ortamında her ders için ayrı request atmak
            # timeout'a sebep olabilir (Vercel limiti 10sn). 
            # O yüzden şimdilik sadece ana notları çekiyoruz.
            # İleride "Detay Getir" butonu yaparsak oraya ekleriz.
            
            raw_text = cols[4].get_text(" ", strip=True)
            my_grades = self._parse_my_grades(raw_text)

            course = {
                "code": cols[1].get_text(strip=True),
                "name": cols[2].get_text(strip=True),
                "letter_grade": cols[6].get_text(strip=True),
                "midterm": my_grades.get("Vize", "-"),
                "final": my_grades.get("Final", "-"),
                "makeup": my_grades.get("Büt", "-"),
                "status": cols[7].get_text(strip=True) if len(cols) > 7 else ""
            }
            grades_list.append(course)

        return {"courses": grades_list, "term_id": donem_val}

    def _parse_my_grades(self, text):
        """ 'Vize : 80 Final : --' stringini parse eder."""
        grades = {}
        vize = re.search(r"Vize\s*:\s*([\d\w-]+)", text)
        final = re.search(r"Final\s*:\s*([\d\w-]+)", text)
        but = re.search(r"Bütünleme\s*:\s*([\d\w-]+)", text)
        
        if vize: grades["Vize"] = vize.group(1)
        if final: grades["Final"] = final.group(1)
        if but: grades["Büt"] = but.group(1)
        return grades


# --- VERCEL HANDLER (API GATEWAY) ---

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            # 1. Gelen Veriyi Oku
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            body = json.loads(post_data.decode('utf-8'))

            # Mobil uygulamadan gelen komut ("action")
            action = body.get('action')
            
            client = OBSClient()

            # --- SENARYO 1: LOGIN SAYFASINI HAZIRLA (Captcha Getir) ---
            if action == 'init_login':
                # Session başlat, captcha indir
                data = client.fetch_login_page()
                self._send_response(200, {"status": "success", "data": data})

            # --- SENARYO 2: GİRİŞ YAP (Credentials + Captcha + Cookie) ---
            elif action == 'login':
                # Önceki adımdan gelen cookie'leri yükle (ÖNEMLİ!)
                client.set_cookies(body.get('cookies'))
                
                result = client.attempt_login(
                    username=body.get('username'),
                    password=body.get('password'),
                    captcha_code=body.get('captcha_code'),
                    view_state_data=body.get('view_state_data') # Bunu da geri yollamalı mobil
                )
                
                if result['success']:
                    self._send_response(200, {"status": "success", "cookies": result['cookies']})
                else:
                    self._send_response(401, {"status": "error", "message": result['message']})

            # --- SENARYO 3: NOTLARI GETİR ---
            elif action == 'get_grades':
                # Login olmuş cookie'leri yükle
                client.set_cookies(body.get('cookies'))
                
                data = client.fetch_grades_data()
                
                if "error" in data:
                    self._send_response(401, {"status": "error", "message": data['error']})
                else:
                    self._send_response(200, {"status": "success", "data": data})

            else:
                self._send_response(400, {"status": "error", "message": "Geçersiz action"})

        except Exception as e:
            self._send_response(500, {"status": "error", "message": str(e)})
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        message = {
            "status": "running", 
            "message": "API calisiyor! Ancak islem yapmak icin POST istegi atmalisin."
        }
        self.wfile.write(json.dumps(message).encode('utf-8'))

    def _send_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()