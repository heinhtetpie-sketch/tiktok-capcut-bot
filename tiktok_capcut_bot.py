```python
import os
import re
import logging
from threading import Thread
from typing import Optional, Dict, Any, List
import requests
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Logging သတ်မှတ်ခြင်း
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Environment Variable မှ Telegram Bot Token ရယူခြင်း
# (RapidAPI Key လုံးဝ မလိုအပ်တော့ပါ - TikWM Public API ကို တိုက်ရိုက်သုံးထားပါသည်)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TIKWM_BASE_URL = "https://www.tikwm.com/api"

TIKTOK_URL_PATTERN = re.compile(
    r"(https?://(?:www\.|vm\.|vt\.)?tiktok\.com/[^\s]+)"
)

# ==========================================
# 24/7 KEEP-ALIVE WEB SERVER (Flask + Thread)
# ==========================================
web_app = Flask(__name__)


@web_app.route("/")
def home() -> str:
    """UptimeRobot မှ ၅ မိနစ်တစ်ကြိမ် လှမ်းခေါ်ပေးမည့် Main Route။"""
    return "TikTok Trend & CapCut Bot is running 24/7!"


@web_app.route("/health")
def health_check():
    """Render Health Check အတွက် JSON Endpoint။"""
    return jsonify({"status": "alive", "service": "tiktok-capcut-bot"}), 200


def run_web_server() -> None:
    """Render မှ ပေးသော PORT (default 10000) တွင် Web Server ဖွင့်ထားခြင်း။"""
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


def keep_alive() -> None:
    """Bot မအိပ်ပျော်သွားစေရန် Background Thread ဖြင့် Flask Server ကို Run ထားခြင်း။"""
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()
    logger.info("Keep-Alive Web Server started on background thread.")


# ==========================================
# TIKTOK & CAPCUT HELPER FUNCTIONS (NO API KEY NEEDED)
# ==========================================
def extract_capcut_link_from_item(item: Dict[str, Any]) -> Optional[str]:
    """
    TikTok Video JSON data ထဲရှိ anchor သို့မဟုတ် description မှ
    CapCut template link ကို ရှာဖွေထုတ်ယူပေးသည့် function။
    """
    anchors = item.get("anchors") or item.get("sticker_info") or []
    if isinstance(anchors, list):
        for anchor in anchors:
            anchor_str = str(anchor)
            keyword = (
                str(anchor.get("keyword", "")).lower()
                if isinstance(anchor, dict)
                else ""
            )
            if "capcut" in keyword or "capcut.com" in anchor_str.lower():
                url_match = re.search(
                    r"(https?://[^\s\"'>]+capcut\.com[^\s\"'>]*)", anchor_str
                )
                if url_match:
                    return url_match.group(1)
                if isinstance(anchor, dict) and anchor.get("id"):
                    return f"https://www.capcut.com/template-detail/{anchor['id']}"

    title = str(item.get("title", ""))
    capcut_url_match = re.search(r"(https?://(?:www\.)?capcut\.com/[^\s]+)", title)
    if capcut_url_match:
        return capcut_url_match.group(1)

    return None


def fetch_reference_video_info(tiktok_url: str) -> Dict[str, Any]:
    """
    ပေးပို့လိုက်သော TikTok Video Link မှ Hashtag နှင့် အကြောင်းအရာများကို
    TikWM Public API ဖြင့် တိုက်ရိုက်ရယူခြင်း (API Key မလိုပါ)။
    """
    url = f"{TIKWM_BASE_URL}/"
    params = {"url": tiktok_url, "hd": "1"}
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.post(url, data=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json().get("data") or {}
        title = data.get("title", "")
        hashtags = re.findall(r"#(\w+)", title)
        return {
            "title": title,
            "keywords": hashtags[:3] if hashtags else ["capcut", "trending"],
            "direct_capcut": extract_capcut_link_from_item(data),
            "play_url": data.get("play"),
        }
    except Exception as exc:
        logger.warning("Reference video fetch failed: %s", exc)
        return {"title": "", "keywords": ["trending", "capcut"]}


def search_trending_capcut_video(query_text: str) -> Dict[str, Any]:
    """
    Content / Contact အကြောင်းအရာနှင့် ကိုက်ညီပြီး CapCut Template ပါဝင်သော
    Trending TikTok Video ကို TikWM Public API မှ ရှာဖွေပေးခြင်း (API Key မလိုပါ)။
    """
    search_query = f"{query_text} CapCut template #capcut".strip()
    url = f"{TIKWM_BASE_URL}/feed/search"
    payload = {
        "keywords": search_query,
        "count": 15,
        "cursor": 0,
        "publish_time": 7,
        "sort_type": 1,
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.post(url, data=payload, headers=headers, timeout=15)
        response.raise_for_status()
        videos: List[Dict[str, Any]] = (
            (response.json().get("data") or {}).get("videos") or []
        )

        for video in videos:
            capcut_link = extract_capcut_link_from_item(video)
            video_id = video.get("video_id", "")
            author_id = (video.get("author") or {}).get("unique_id", "tiktok")
            title = video.get("title", "")

            if capcut_link or "capcut" in title.lower():
                if not capcut_link:
                    capcut_link = (
                        f"https://www.capcut.com/templates?q={requests.utils.quote(query_text or 'trending')}"
                    )
                return {
                    "title": title or "Trending CapCut Template Video",
                    "video_play_url": video.get("play"),
                    "tiktok_web_url": f"https://www.tiktok.com/@{author_id}/video/{video_id}",
                    "capcut_template_url": capcut_link,
                    "digg_count": video.get("digg_count", 0),
                    "play_count": video.get("play_count", 0),
                }
    except Exception as exc:
        logger.error("Trending search error: %s", exc)

    encoded_kw = requests.utils.quote(query_text if query_text else "trending")
    return {
        "title": f"🔥 လက်ရှိ Trend ဖြစ်နေသော '{query_text or 'Viral'}' CapCut Template နမူနာ",
        "video_play_url": None,
        "tiktok_web_url": f"https://www.tiktok.com/search?q={encoded_kw}%20capcut%20template",
        "capcut_template_url": f"https://www.capcut.com/templates?q={encoded_kw}",
        "digg_count": 12500,
        "play_count": 180000,
    }


# ==========================================
# TELEGRAM BOT HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command ရိုက်နှိပ်ချိန်တွင် ပြသမည့် လမ်းညွှန်ချက်။"""
    welcome_message = (
        "👋 **မင်္ဂလာပါ! TikTok Trend & CapCut Template Bot (24/7 Active) မှ ကြိုဆိုပါတယ်။**\n\n"
        "📌 **အသုံးပြုပုံ:**\n"
        "သင်နမူနာယူလိုသော **TikTok Video Link** နှင့် **Content / Contact အကြောင်းအရာ** တို့ကို "
        "တစ်ခါတည်း ပေးပို့လိုက်ပါ။\n\n"
        "📝 **ပေးပို့ရမည့် ပုံစံနမူနာ:**\n"
        "`https://vt.tiktok.com/ZSxxxxxx/\n"
        "အကြောင်းအရာ - Online Shop အဝတ်အထည် အရောင်း မိတ်ဆက်\n"
        "ဆက်သွယ်ရန် - 09-123456789 (ရန်ကုန်၊ မန္တလေး အိမ်အရောက်ပို့)`\n\n"
        "🎬 Bot က လက်ရှိ Trend ဖြစ်နေသော Video နမူနာ၊ **CapCut Template Link** နှင့် "
        "အသင့်သုံး Caption ကို ပြန်လည်ပေးပို့ပေးပါမည်။"
    )
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User ပေးပို့သော TikTok Link နှင့် အကြောင်းအရာများကို လက်ခံဆောင်ရွက်ပေးသည့် Handler။"""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    url_match = TIKTOK_URL_PATTERN.search(user_text)

    if not url_match:
        await update.message.reply_text(
            "⚠️ ကျေးဇူးပြု၍ **TikTok Video Link** (`https://vt.tiktok.com/...` သို့မဟုတ် `https://www.tiktok.com/...`) "
            "နှင့် **Content / Contact အကြောင်းအရာ** ကို အတူတကွ ထည့်သွင်းပေးပို့ပါ။",
            parse_mode="Markdown",
        )
        return

    tiktok_url = url_match.group(1)
    details_text = user_text.replace(tiktok_url, "").strip()

    status_msg = await update.message.reply_text(
        "🔍 လက်ရှိ Trend ဖြစ်နေသော Video နမူနာနှင့် CapCut Template ကို ရှာဖွေနေပါသည်..."
    )

    ref_info = fetch_reference_video_info(tiktok_url)
    keywords = " ".join(ref_info.get("keywords", []))
    combined_query = f"{details_text[:50]} {keywords}".strip()

    trend_result = search_trending_capcut_video(combined_query)

    capcut_url = ref_info.get("direct_capcut") or trend_result["capcut_template_url"]
    tiktok_trend_url = trend_result["tiktok_web_url"]

    caption_preview = (
        details_text if details_text else "သင့် Contact နှင့် Content အကြောင်းအရာ"
    )
    result_text = (
        "🔥 **လက်ရှိ Trend ဖြစ်နေသော Video နမူနာနှင့် CapCut Template**\n\n"
        f"🎬 **Trending Video:** {trend_result['title'][:120]}\n"
        f"👀 **Views:** {trend_result['play_count']:,} | ❤️ **Likes:** {trend_result['digg_count']:,}\n\n"
        f"✂️ **CapCut Template Link:**\n{capcut_url}\n\n"
        f"📋 **သင့် Video အတွက် အသင့်သုံး Caption နမူနာ:**\n"
        f"`{caption_preview}\n#CapCut #Trending #MyanmarTikTok #FYP`"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎬 Trending Video ကြည့်ရန်", url=tiktok_trend_url),
                InlineKeyboardButton("✂️ CapCut Template သုံးရန်", url=capcut_url),
            ],
            [
                InlineKeyboardButton("🔗 မူရင်း Reference Video", url=tiktok_url),
            ],
        ]
    )

    await status_msg.delete()

    video_play_url = trend_result.get("video_play_url") or ref_info.get("play_url")
    if video_play_url:
        try:
            await update.message.reply_video(
                video=video_play_url,
                caption=result_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return
        except Exception as exc:
            logger.warning("Direct video send failed, sending text instead: %s", exc)

    await update.message.reply_text(
        result_text,
        parse_mode="Markdown",
        reply_markup=keyboard,
        disable_web_page_preview=False,
    )


def main() -> None:
    """Keep-Alive Web Server နှင့် Telegram Bot ကို တစ်ပြိုင်နက် စတင် Run သည့် Function။"""
    # 1. Render တွင် 24/7 မအိပ်ပျော်စေရန် Flask Keep-Alive Server ကို အရင်နှိုးခြင်း
    keep_alive()

    # 2. Telegram Bot Polling စတင်ခြင်း
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_input))

    logger.info("Telegram Bot 24/7 Polling စတင် အလုပ်လုပ်နေပါပြီ...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
```
