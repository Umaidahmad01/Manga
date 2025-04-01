import requests
from bs4 import BeautifulSoup
import os
import sqlite3
from datetime import datetime
import img2pdf
from urllib.parse import urljoin
import logging
import getpass
import sys
import re

class MangaScraper:
    def __init__(self, db_name="manga.db", log_file="manga_scraper.log"):
        # Logging setup
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger()
        self.logger.info("MangaScraper initialized")
        
        # Database setup
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS manga_downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                pdf_name TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        ''')
        self.conn.commit()
        self.logger.info("Database tables created or already exist")

    def add_auth_user(self, username, password):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO auth_users (username, password)
                VALUES (?, ?)
            ''', (username, password))
            self.conn.commit()
            self.logger.info(f"New authorized user added: {username}")
            print(f"User '{username}' added successfully!")
        except sqlite3.IntegrityError:
            self.logger.warning(f"Username '{username}' already exists")
            print(f"Username '{username}' already exists. Try a different username.")

    def get_auth_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT username, password FROM auth_users")
        return {row[0]: row[1] for row in cursor.fetchall()}

    def add_download(self, url, pdf_name):
        cursor = self.conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO manga_downloads (url, pdf_name, timestamp)
            VALUES (?, ?, ?)
        ''', (url, pdf_name, timestamp))
        self.conn.commit()
        self.logger.info(f"Added to database: {url} -> {pdf_name}")
        print(f"Added to database: {url} -> {pdf_name}")

    def get_all_downloads(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM manga_downloads")
        return cursor.fetchall()

    def authenticate(self):
        auth_users = self.get_auth_users()
        if not auth_users:
            self.logger.warning("No authorized users found. Add users using /add_auth")
            print("No authorized users found. Please add a user first using /add_auth.")
            return False
        
        attempts = 3
        while attempts > 0:
            username = input("Enter username: ")
            password = getpass.getpass("Enter password: ")
            
            if username in auth_users and auth_users[username] == password:
                self.logger.info(f"User '{username}' authenticated successfully")
                print("Authentication successful!")
                return True
            else:
                attempts -= 1
                self.logger.warning(f"Authentication failed for user '{username}'. Attempts left: {attempts}")
                print(f"Wrong username or password. {attempts} attempts left.")
        
        self.logger.error("Authentication failed: Max attempts reached")
        print("Too many failed attempts. Access denied.")
        return False

    def download_images_to_pdf(self, url, output_pdf_name):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.logger.info(f"Attempting to access URL: {url}")
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            self.logger.error(f"Failed to get response from {url}. Status code: {response.status_code}")
            print("URL se response nahi mila. Check kar link sahi hai ya nahi.")
            return
        
        soup = BeautifulSoup(response.content, 'html.parser')
        # Specific to mangahindisub.in - targeting manga images
        img_tags = soup.find_all('img', class_=re.compile('wp-manga-chapter-img|img-responsive|lazyload'))
        if not img_tags:
            self.logger.warning(f"No manga images found on {url}")
            print("Koi manga images nahi mili webpage pe.")
            return
        
        temp_folder = "temp_images"
        if not os.path.exists(temp_folder):
            os.makedirs(temp_folder)
            self.logger.info(f"Created temporary folder: {temp_folder}")
        
        image_paths = []
        base_url = url
        
        for idx, img in enumerate(img_tags):
            img_url = img.get('src') or img.get('data-src')  # Handle lazy-loaded images
            if not img_url:
                continue
            
            img_url = urljoin(base_url, img_url)
            try:
                self.logger.info(f"Downloading image: {img_url}")
                img_response = requests.get(img_url, headers=headers)
                if img_response.status_code == 200:
                    img_path = os.path.join(temp_folder, f"image_{idx}.jpg")
                    with open(img_path, 'wb') as f:
                        f.write(img_response.content)
                    image_paths.append(img_path)
                    self.logger.info(f"Successfully downloaded: {img_url}")
                    print(f"Downloaded: {img_url}")
                else:
                    self.logger.warning(f"Failed to download {img_url}. Status code: {img_response.status_code}")
                    print(f"Failed to download: {img_url}")
            except Exception as e:
                self.logger.error(f"Error downloading {img_url}: {e}")
                print(f"Error downloading {img_url}: {e}")
        
        if image_paths:
            self.logger.info(f"Creating PDF: {output_pdf_name}")
            print("PDF banaya ja raha hai...")
            with open(output_pdf_name, "wb") as f:
                f.write(img2pdf.convert(image_paths))
            self.logger.info(f"PDF created: {output_pdf_name}")
            print(f"PDF ban gaya: {output_pdf_name}")
            self.add_download(url, output_pdf_name)
            
            for img_path in image_paths:
                os.remove(img_path)
                self.logger.info(f"Deleted temporary file: {img_path}")
            os.rmdir(temp_folder)
            self.logger.info(f"Deleted temporary folder: {temp_folder}")
        else:
            self.logger.warning("No images downloaded, PDF not created")
            print("Koi image download nahi hui, PDF nahi banega.")

    def close(self):
        self.conn.close()
        self.logger.info("Database connection closed")

# Usage with command-line argument support
if __name__ == "__main__":
    scraper = MangaScraper()
    
    # Check for commands
    if len(sys.argv) > 1:
        if sys.argv[1] == "/add_auth":
            if len(sys.argv) != 4:
                print("Usage: python mangahindisub_scraper.py /add_auth <username> <password>")
                scraper.close()
                exit()
            username = sys.argv[2]
            password = sys.argv[3]
            scraper.add_auth_user(username, password)
            scraper.close()
            exit()
        
        elif sys.argv[1] == "/download":
            if len(sys.argv) < 3 or "-n" not in sys.argv:
                print("Usage: python mangahindisub_scraper.py /download <url> -n <new_file_name>")
                scraper.close()
                exit()
            url = sys.argv[2]
            if not scraper.authenticate():
                scraper.close()
                exit()
            new_file_name_idx = sys.argv.index("-n") + 1
            if new_file_name_idx >= len(sys.argv):
                print("Please provide a new file name after -n")
                scraper.close()
                exit()
            new_file_name = sys.argv[new_file_name_idx]
            if not new_file_name.endswith('.pdf'):
                new_file_name += '.pdf'
            scraper.download_images_to_pdf(url, new_file_name)
            scraper.close()
            exit()
    
    # Normal interactive flow
    if not scraper.authenticate():
        scraper.close()
        exit()
    
    manga_url = input("Manga page ka URL daal: ")
    pdf_name = input("PDF ka naam kya rakhna hai (e.g., manga.pdf): ")
    if not pdf_name.endswith('.pdf'):
        pdf_name += '.pdf'
    scraper.download_images_to_pdf(manga_url, pdf_name)
    
    downloads = scraper.get_all_downloads()
    print("\nDatabase mein entries:")
    for download in downloads:
        print(download)
    
    scraper.close()
