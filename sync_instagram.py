import os
import glob
import json
import subprocess
import time
from playwright.sync_api import sync_playwright

def cleanup_old_media(allowed_files):
    """Remove arquivos antigos de mídia que não estão na lista dos 12 ativos"""
    for file_path in glob.glob("media_*.*") + glob.glob("video_*.mp4"):
        if file_path not in allowed_files:
            try:
                os.remove(file_path)
                print(f"🗑️ Mídia antiga removida: {file_path}")
            except Exception as e:
                print(f"Erro ao remover {file_path}: {e}")

def main():
    cookies_raw = os.environ.get("INSTAGRAM_COOKIES", "")
    cookie_file = "cookies.txt"
    with open(cookie_file, "w", encoding="utf-8") as f:
        f.write(cookies_raw)

    playwright_cookies = []
    for line in cookies_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            domain, _, path, secure, expires, name, value = parts[:7]
            playwright_cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": secure.lower() == "true",
                "expires": float(expires) if expires.isdigit() else -1
            })

    username = "speedmotos.consomax"
    target_count = 12
    posts_urls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        if playwright_cookies:
            context.add_cookies(playwright_cookies)

        page = context.new_page()
        print(f"Acessando feed de @{username}...")

        try:
            page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(6)

            for _ in range(8):
                page.mouse.wheel(0, 1000)
                time.sleep(2)

            elements = page.query_selector_all("a[href*='/p/'], a[href*='/reel/']")
            
            for el in elements:
                is_pinned = False
                try:
                    pin_elem = el.query_selector("svg[aria-label*='Pin'], svg[aria-label*='Fixado'], svg[title*='Pin'], svg[title*='Fixado']")
                    if pin_elem:
                        is_pinned = True
                except Exception:
                    pass

                if is_pinned:
                    print("📌 Post fixado ignorado.")
                    continue

                href = el.get_attribute("href")
                if href:
                    full_url = f"https://www.instagram.com{href}" if href.startswith("/") else href
                    clean_url = full_url.split("?")[0]
                    if clean_url not in posts_urls:
                        posts_urls.append(clean_url)
                
                if len(posts_urls) >= target_count:
                    break

        except Exception as e:
            print(f"Aviso durante navegação: {e}")

        browser.close()

    print(f"\nTotal de posts cronológicos localizados: {len(posts_urls)}")

    if not posts_urls:
        print("❌ Nenhum post foi identificado.")
        return

    posts_data = []
    allowed_files = []

    for idx, post_url in enumerate(posts_urls[:target_count], start=1):
        print(f"\n--- Processando Post #{idx}: {post_url} ---")
        
        caption = ""
        is_video = False
        
        # 1. Obter metadados via yt-dlp
        try:
            desc_cmd = [
                "yt-dlp",
                "--cookies", cookie_file,
                "--no-check-certificates",
                "--dump-json",
                post_url
            ]
            info_res = subprocess.run(desc_cmd, capture_output=True, text=True)
            if info_res.stdout:
                info_json = json.loads(info_res.stdout)
                caption = info_json.get("description") or info_json.get("title") or ""
                
                # Checa se possui stream de vídeo
                if info_json.get("vcodec") and info_json.get("vcodec") != "none":
                    is_video = True
                elif info_json.get("formats"):
                    for fmt in info_json.get("formats", []):
                        if fmt.get("vcodec") and fmt.get("vcodec") != "none":
                            is_video = True
                            break
        except Exception as e:
            print(f"Erro ao extrair metadados: {e}")

        if is_video:
            output_filename = f"media_{idx}.mp4"
            temp_raw = f"temp_raw_{idx}.mp4"
            allowed_files.append(output_filename)

            # Baixa vídeo
            cmd_download = [
                "yt-dlp",
                "--cookies", cookie_file,
                "--no-check-certificates",
                "-f", "bestvideo+bestaudio/best",
                "-o", temp_raw,
                "--force-overwrites",
                post_url
            ]
            subprocess.run(cmd_download, capture_output=True, text=True)

            # Comprime em 720p H.264
            if os.path.exists(temp_raw):
                cmd_ffmpeg = [
                    "ffmpeg", "-y",
                    "-i", temp_raw,
                    "-vf", "scale='min(720,iw)':-2",
                    "-c:v", "libx264",
                    "-crf", "26",
                    "-preset", "veryfast",
                    "-c:a", "aac",
                    "-b:a", "96k",
                    "-movflags", "+faststart",
                    output_filename
                ]
                subprocess.run(cmd_ffmpeg, capture_output=True, text=True)
                try:
                    os.remove(temp_raw)
                except Exception:
                    pass

            posts_data.append({
                "id": idx,
                "type": "video",
                "url": post_url,
                "media_file": output_filename,
                "caption": caption.strip() if caption else "Speed Motos Consomax - Acelere seu sonho sobre duas rodas!",
                "updated_at": time.strftime("%d/%m/%Y às %H:%M")
            })

        else:
            # Baixa e converte imagem para JPG
            output_filename = f"media_{idx}.jpg"
            temp_thumb = f"temp_thumb_{idx}"
            allowed_files.append(output_filename)

            cmd_thumb = [
                "yt-dlp",
                "--cookies", cookie_file,
                "--no-check-certificates",
                "--write-thumbnail",
                "--skip-download",
                "-o", temp_thumb,
                "--force-overwrites",
                post_url
            ]
            subprocess.run(cmd_thumb, capture_output=True, text=True)

            # Converte a thumbnail gerada (independente se veio webp, png ou jpg) para jpg padrão
            found_thumb = None
            for f in glob.glob(f"{temp_thumb}.*"):
                found_thumb = f
                break

            if found_thumb and os.path.exists(found_thumb):
                cmd_conv = [
                    "ffmpeg", "-y",
                    "-i", found_thumb,
                    "-q:v", "2",
                    output_filename
                ]
                subprocess.run(cmd_conv, capture_output=True, text=True)
                try:
                    os.remove(found_thumb)
                except Exception:
                    pass

            posts_data.append({
                "id": idx,
                "type": "image",
                "url": post_url,
                "media_file": output_filename,
                "caption": caption.strip() if caption else "Speed Motos Consomax - As melhores motos e condições exclusivas!",
                "updated_at": time.strftime("%d/%m/%Y às %H:%M")
            })

    cleanup_old_media(allowed_files)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(posts_data, f, ensure_ascii=False, indent=2)

    if os.path.exists(cookie_file):
        os.remove(cookie_file)

    print("\n✅ Concluído! 12 posts (vídeos e fotos) baixados e organizados com sucesso.")

if __name__ == "__main__":
    main()
