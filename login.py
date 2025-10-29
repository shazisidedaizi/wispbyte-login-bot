# login.py
import os
import asyncio
import aiohttp
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ===================== 配置 =====================
LOGIN_URL = "https://wispbyte.com/client/servers"

# ===================== Telegram 通知 =====================
async def tg_notify(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("Warning: 未设置 TG_BOT_TOKEN / TG_CHAT_ID，跳过通知")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })
        except Exception as e:
            print(f"Warning: Telegram 消息发送失败: {e}")

async def tg_notify_photo(photo_path: str, caption: str = ""):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    async with aiohttp.ClientSession() as session:
        try:
            with open(photo_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", chat_id)
                data.add_field("photo", f, filename=os.path.basename(photo_path))
                if caption:
                    data.add_field("caption", caption)
                    data.add_field("parse_mode", "HTML")
                await session.post(url, data=data)
        except Exception as e:
            print(f"Warning: Telegram 图片发送失败: {e}")
        finally:
            try:
                os.remove(photo_path)
            except:
                pass

# ===================== 报告生成 =====================
def build_report(results, start_time, end_time):
    success = [r for r in results if r["success"]]
    failed  = [r for r in results if not r["success"]]

    lines = [
        "Searcade 自动登录报告",
        f"目标: <a href='{LOGIN_URL}'>服务器 #3759</a>",
        f"时间: {start_time} → {end_time}",
        f"结果: <b>{len(success)} 成功</b> | <b>{len(failed)} 失败</b>",
        ""
    ]

    if success:
        lines.append("Success 成功：")
        lines.extend([f"   • <code>{r['email']}</code>" for r in success])
        lines.append("")

    if failed:
        lines.append("Failed 失败：")
        lines.extend([f"   • <code>{r['email']}</code>" for r in failed])

    return "\n".join(lines)

# ===================== 单账号登录 =====================
async def login_one(email: str, password: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--window-size=1920,1080"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        result = {"email": email, "success": False}

        try:
            print(f"[{email}] 访问后台...")
            await page.goto(LOGIN_URL, wait_until="networkidle")
            current_url = page.url
            print(f"[{email}] 当前URL: {current_url}")

            if "servers/3759" in current_url and "login" not in current_url.lower():
                print(f"[{email}] 已登录！")
                result["success"] = True
                return result

            await page.wait_for_selector('button:has-text("Login")', timeout=15000)
            print(f"[{email}] 检测到登录页")

            await page.fill('input[type="text"] >> nth=0', email)
            await page.fill('input[type="password"] >> nth=0', password)
            await page.click('button:has-text("Login")')
            print(f"[{email}] 提交登录")

            await page.wait_for_url("**/servers/3759", timeout=20000)
            print(f"[{email}] 登录成功！")
            result["success"] = True

        except Exception as e:
            screenshot = f"error_{email.replace('@', '_')}_{int(datetime.now().timestamp())}.png"
            await page.screenshot(path=screenshot, full_page=True)
            await tg_notify_photo(screenshot,
                caption=f"Searcade 登录失败\n"
                        f"账号: <code>{email}</code>\n"
                        f"错误: <i>{str(e)[:200]}</i>\n"
                        f"URL: {page.url}"
            )
            print(f"[{email}] 登录失败: {e}")
        finally:
            await context.close()
            await browser.close()
            return result

# ===================== 主流程 =====================
async def main():
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"登录任务开始: {start_time}")

    accounts_str = os.getenv("LOGIN_ACCOUNTS")
    if not accounts_str:
        await tg_notify("Failed: 未配置任何账号")
        return

    accounts = [a.strip() for a in accounts_str.split(",") if ":" in a]
    if not accounts:
        await tg_notify("Failed: LOGIN_ACCOUNTS 格式错误，应为 email:password")
        return

    tasks = [login_one(email, pwd) for acc in accounts for email, pwd in [acc.split(":", 1)]]
    results = await asyncio.gather(*tasks)

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_msg = build_report(results, start_time, end_time)
    await tg_notify(final_msg)
    print(final_msg)

# ===================== 启动 =====================
if __name__ == "__main__":
    asyncio.run(main())
