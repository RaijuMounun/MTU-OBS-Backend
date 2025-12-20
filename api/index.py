from http.server import BaseHTTPRequestHandler
import json
import requests
from bs4 import BeautifulSoup
import base64

class OBSClient:
    # URL SABİTLERİ (Senin okulunun adresleri)
    BASE_URL = "https://obs.ozal.edu.tr/oibs/std/"
    LOGIN_URL = "https://obs.ozal.edu.tr/oibs/std/login.aspx"
    GRADES_URL = "https://obs.ozal.edu.tr/oibs/std/not_listesi_op.aspx"

    def __init__(self):
        self.session = requests.Session()
        # Headerları güçlendirelim (Chrome gibi davransın)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": self.LOGIN_URL,
            "Origin": "https://obs.ozal.edu.tr",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })

    def get_cookies(self):
        return requests.utils.dict_from_cookiejar(self.session.cookies)

    def set_cookies(self, cookie_dict):
        if cookie_dict:
            requests.utils.add_dict_to_cookiejar(self.session.cookies, cookie_dict)

    def _get_hidden_inputs(self, soup):
        data = {}
        for inp in soup.find_all("input", type="hidden"):
            if inp.get("name"):
                data[inp.get("name")] = inp.get("value", "")
        return data

    def fetch_login_page(self):
        try:
            # 1. Sayfaya Git
            r = self.session.get(self.LOGIN_URL)
            
            # DEBUG: Eğer sayfa açılmazsa kodu burada kesip hatayı dönelim
            if r.status_code != 200:
                return {"error": f"Siteye erişilemedi. Status: {r.status_code}"}

            soup = BeautifulSoup(r.content, "html.parser")
            title = soup.title.string if soup.title else "Baslik Yok"

            # 2. Captcha Resmini Bul
            captcha_b64 = None
            img_tag = soup.find(id="imgCaptchaImg")
            
            debug_info = f"Site: {title}" # Sayfa başlığını loglayalım

            if img_tag:
                src = img_tag.get("src")
                # URL düzeltme
                if not src.startswith("http"):
                    url = self.BASE_URL + src.lstrip("/") if src.startswith("/") else self.BASE_URL + src
                else:
                    url = src
                
                # Resmi İndir
                r_img = self.session.get(url)
                if r_img.status_code == 200:
                    captcha_b64 = base64.b64encode(r_img.content).decode('utf-8')
                else:
                    debug_info += f" | Resim indirilemedi: {r_img.status_code}"
            else:
                debug_info += " | Captcha elementi (imgCaptchaImg) bulunamadi!"

            # 3. Hidden Inputları al
            hidden_inputs = self._get_hidden_inputs(soup)

            return {
                "captcha_image": captcha_b64,
                "view_state_data": hidden_inputs,
                "cookies": self.get_cookies(),
                "debug": debug_info # Flutter logunda bunu göreceğiz
            }

        except Exception as e:
            return {"error": f"Backend Hatasi: {str(e)}"}

    # ... (Diğer metodlar: attempt_login, fetch_grades_data aynen kalabilir) ...
    # Kısalık olsun diye attempt_login ve fetch_grades_data'yı buraya tekrar yapıştırmıyorum.
    # Onları silme sakın! Sadece fetch_login_page'i güncelle.
    # Eğer emin değilsen söyle tam halini atayım.

# --- HANDLER ---
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            body = json.loads(post_data.decode('utf-8'))
            action = body.get('action')
            
            client = OBSClient()

            if action == 'init_login':
                data = client.fetch_login_page()
                # Debug bilgisini status'a da ekleyelim ki görelim
                if "error" in data:
                     self._send_response(500, {"status": "error", "message": data['error']})
                else:
                     self._send_response(200, {"status": "success", "data": data})

            # ... Diğer action'lar (login, get_grades) buraya gelecek ...
            # Önceki kodundaki handler mantığının aynısı.

        except Exception as e:
            self._send_response(500, {"status": "error", "message": str(e)})

    def _send_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def do_GET(self):
         self._send_response(200, {"status": "alive", "message": "POST atin."})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()