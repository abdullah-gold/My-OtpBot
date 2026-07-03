"""
NOX SMS — OTP Bot with Admin Panel + Range Management
======================================================
Install:  pip install "python-telegram-bot>=22.7" requests
Run:      python nox_bot.py
"""

import re, logging, threading, time, json, os, requests, uuid
try:
    from langdetect import detect as _langdetect
    LANGDETECT_OK = True
except ImportError:
    LANGDETECT_OK = False
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN      = "8552766921:AAFG_7knD0fJl0ryXZy1gco_N8wcEUpTX5w"
ADMIN_CHAT_ID  = "8484930932"
OTP_GROUP_ID   = "-1003923598919"
OTP_GROUP_LINK = "https://t.me/nox_otp"

GET_NUMBER_LINK      = "https://t.me/noxsms_panel_bot"
COMMUNITY_GROUP_LINK = "https://t.me/nox_community_hub"

FASTX_BASE   = "https://fastxotps.com/api"
FASTX_KEY    = "MURAD_E308F86FCAA765EFF1553B1B"
STEX_BASE    = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"
STEX_KEY     = "MYRXEJAKXGQ"

OTP_PATTERN     = re.compile(r"\b(\d{4,8})\b")
RANGES_FILE     = "ranges.json"
ADMINS_FILE     = "admins.json"
group_sent_otps = set()

NUMBERS_PER_BATCH = 3

SERVICES = {
    "Facebook":  "📘",
    "Instagram": "📸",
    "WhatsApp":  "💬",
    "Telegram":  "✈️",
}
PANELS = ["FastX", "Stex"]

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def load_ranges():
    if os.path.exists(RANGES_FILE):
        try:
            return json.load(open(RANGES_FILE, encoding="utf-8"))
        except:
            pass
    return {}

def save_ranges(data):
    json.dump(data, open(RANGES_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def load_admins():
    if os.path.exists(ADMINS_FILE):
        try:
            return json.load(open(ADMINS_FILE, encoding="utf-8"))
        except:
            pass
    return []

def save_admins(data):
    json.dump(data, open(ADMINS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def is_owner(chat_id):
    return str(chat_id) == str(ADMIN_CHAT_ID)

def is_admin(chat_id):
    return is_owner(chat_id) or str(chat_id) in load_admins()

def add_admin(chat_id):
    admins = load_admins()
    cid = str(chat_id)
    if cid not in admins and cid != str(ADMIN_CHAT_ID):
        admins.append(cid)
        save_admins(admins)
        return True
    return False

def remove_admin(chat_id):
    admins = load_admins()
    cid = str(chat_id)
    if cid in admins:
        admins.remove(cid)
        save_admins(admins)
        return True
    return False

# ─────────────────────────────────────────────
# ✅ FIXED: Cookie সরানো হয়েছে
# ─────────────────────────────────────────────
def fastx_headers(is_json=False):
    h = {
        "X-API-Key": FASTX_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fastxotps.com/",
        "Origin": "https://fastxotps.com",
    }
    if is_json:
        h["Content-Type"] = "application/json"
    return h  # ✅ Cookie নেই — Cloudflare block হবে না

def is_cloudflare_block(response):
    if "text/html" in response.headers.get("Content-Type", ""):
        return True
    if "turnstile" in response.text.lower() or "checking your connection" in response.text.lower():
        return True
    return False

def fastx_get_number(rng):
    try:
        h = fastx_headers(is_json=True)
        r = requests.post(f"{FASTX_BASE}/getnum", json={"range": rng}, headers=h, timeout=15)
        if not r.text or not r.text.strip():
            logger.error(f"[FastX getnum] Empty response")
            return None
        if is_cloudflare_block(r):
            logger.error(f"[FastX getnum] Cloudflare block!")
            return None
        d = r.json()
        meta_code = (d.get("meta") or {}).get("code")
        data_obj  = d.get("data") or {}
        if meta_code == 200 and data_obj:
            number  = (data_obj.get("full_number") or
                       data_obj.get("no_plus_number") or
                       data_obj.get("national_number"))
            country = data_obj.get("country", "Unknown")
            if number:
                if not str(number).startswith("+"):
                    number = "+" + str(number)
                return {"number": number, "country": country, "source": "FastX"}
        if meta_code == 2946:
            logger.warning(f"[FastX] Out of stock: {rng}")
        return None
    except Exception as e:
        logger.error(f"❌ FastX getnum: {e}")
        return None

def stex_get_number(rng):
    try:
        rid_clean = re.sub(r'[Xx]+$', '', str(rng)).strip()
        h = {"mauthapi": STEX_KEY, "Content-Type": "application/json"}
        r = requests.post(f"{STEX_BASE}/getnum", json={"rid": rid_clean}, headers=h, timeout=15)
        d = r.json()
        logger.info(f"[Stex getnum] {d}")
        if (d.get("meta") or {}).get("code") == 200:
            pd = d.get("data") or {}
            num = pd.get("full_number") or pd.get("no_plus_number") or ""
            if num and not str(num).startswith("+"):
                num = "+" + str(num)
            return {"number": num, "country": pd.get("country", "Unknown"), "source": "Stex"}
        return None
    except Exception as e:
        logger.error(f"❌ Stex getnum: {e}")
        return None

def get_number(panel, rng):
    if panel == "FastX":
        return fastx_get_number(rng)
    return stex_get_number(rng)

def normalize_range(rng):
    rng = str(rng).strip()
    if rng.upper().endswith("XXX"):
        return rng
    if "X" in rng.upper():
        return rng
    return rng + "XXX"

def get_numbers_batch(panel, rng, count=NUMBERS_PER_BATCH):
    rng = normalize_range(rng)
    logger.info(f"[Batch] panel={panel} range={rng}")
    results = []
    for i in range(count):
        r = get_number(panel, rng)
        if r and r.get("number"):
            results.append(r)
        else:
            logger.warning(f"[Batch] #{i+1} failed for {rng}")
            break
    logger.info(f"[Batch] Got {len(results)} numbers")
    return results

def fastx_get_otps():
    try:
        h = fastx_headers()
        r = requests.get(f"{FASTX_BASE}/otps", headers=h, timeout=15)
        if not r.text or not r.text.strip():
            return []
        if is_cloudflare_block(r):
            logger.error("[FastX otps] Cloudflare block!")
            return []
        d = r.json()
        if (d.get("meta") or {}).get("code") == 200:
            return (d.get("data") or {}).get("otps") or []
        return []
    except Exception as e:
        logger.error(f"❌ FastX otps: {e}")
        return []

def stex_get_otps():
    try:
        h = {"mauthapi": STEX_KEY}
        r = requests.get(f"{STEX_BASE}/success-otp", headers=h, timeout=15)
        if not r.text or not r.text.strip():
            return []
        d = r.json()
        if (d.get("meta") or {}).get("code") == 200:
            raw = (d.get("data") or {}).get("otps") or []
            result = []
            for item in raw:
                num = str(item.get("number", ""))
                if num and not num.startswith("+"):
                    num = "+" + num
                msg = item.get("message", "")
                m = OTP_PATTERN.search(msg)
                result.append({
                    "number":  num,
                    "otp":     m.group(1) if m else "",
                    "message": msg,
                    "sms":     msg,
                })
            return result
        return []
    except Exception as e:
        logger.error(f"❌ Stex otps: {e}")
        return []

def fastx_get_console():
    try:
        h = fastx_headers()
        r = requests.get(f"{FASTX_BASE}/otps", headers=h, timeout=15)
        if not r.text or not r.text.strip():
            return []
        if is_cloudflare_block(r):
            logger.error("[FastX console] Cloudflare block!")
            return []
        d = r.json()
        otps = []
        if (d.get("meta") or {}).get("code") == 200:
            otps = (d.get("data") or {}).get("otps") or []
        hits = []
        for item in otps:
            hits.append({
                "number":  item.get("number", ""),
                "message": item.get("sms", "") or item.get("message", ""),
                "otp":     item.get("otp", ""),
                "sid":     item.get("platform", "Unknown"),
            })
        logger.info(f"[FastX console] {len(hits)} hits")
        return hits
    except Exception as e:
        logger.error(f"❌ FastX console: {e}")
        return []

def stex_get_console():
    try:
        h = {"mauthapi": STEX_KEY}
        r = requests.get(f"{STEX_BASE}/console", headers=h, timeout=15)
        if not r.text or not r.text.strip():
            return []
        d = r.json()
        if (d.get("meta") or {}).get("code") != 200:
            logger.warning(f"[Stex console] {d.get('message')}")
            return []
        raw_hits = (d.get("data") or {}).get("hits") or []
        hits = []
        for item in raw_hits:
            hits.append({
                "number":  item.get("range", ""),
                "message": item.get("message", ""),
                "otp":     "",
                "sid":     item.get("sid", "Unknown"),
            })
        logger.info(f"[Stex console] {len(hits)} hits")
        return hits
    except Exception as e:
        logger.error(f"❌ Stex console: {e}")
        return []

def mask_number(n):
    c = re.sub(r'\D', '', str(n))
    return ("+" + c[:6] + "-NOX-" + c[-4:]) if len(c) > 4 else str(n)

COUNTRY_TO_ISO = {
    "afghanistan":"AF","albania":"AL","algeria":"DZ","argentina":"AR","armenia":"AM",
    "australia":"AU","austria":"AT","azerbaijan":"AZ","bahrain":"BH","bangladesh":"BD",
    "belarus":"BY","belgium":"BE","benin":"BJ","bolivia":"BO","bosnia":"BA","botswana":"BW",
    "brazil":"BR","brunei":"BN","bulgaria":"BG","burkina faso":"BF","burundi":"BI",
    "cambodia":"KH","cameroon":"CM","canada":"CA","chad":"TD","chile":"CL","china":"CN",
    "colombia":"CO","congo":"CG","costa rica":"CR","croatia":"HR","cuba":"CU","cyprus":"CY",
    "czech republic":"CZ","czechia":"CZ","denmark":"DK","djibouti":"DJ",
    "dominican republic":"DO","ecuador":"EC","egypt":"EG","el salvador":"SV",
    "estonia":"EE","ethiopia":"ET","finland":"FI","france":"FR","gabon":"GA",
    "gambia":"GM","georgia":"GE","germany":"DE","ghana":"GH","greece":"GR",
    "guatemala":"GT","guinea":"GN","haiti":"HT","honduras":"HN","hong kong":"HK",
    "hungary":"HU","iceland":"IS","india":"IN","indonesia":"ID","iran":"IR","iraq":"IQ",
    "ireland":"IE","israel":"IL","italy":"IT","ivory coast":"CI","cote d'ivoire":"CI",
    "cote d ivoire":"CI","jamaica":"JM","japan":"JP","jordan":"JO","kazakhstan":"KZ",
    "kenya":"KE","kuwait":"KW","kyrgyzstan":"KG","laos":"LA","latvia":"LV","lebanon":"LB",
    "liberia":"LR","libya":"LY","lithuania":"LT","luxembourg":"LU","madagascar":"MG",
    "malawi":"MW","malaysia":"MY","maldives":"MV","mali":"ML","malta":"MT",
    "mauritania":"MR","mauritius":"MU","mexico":"MX","moldova":"MD","mongolia":"MN",
    "montenegro":"ME","morocco":"MA","mozambique":"MZ","myanmar":"MM","namibia":"NA",
    "nepal":"NP","netherlands":"NL","new zealand":"NZ","nicaragua":"NI","niger":"NE",
    "nigeria":"NG","north korea":"KP","north macedonia":"MK","norway":"NO","oman":"OM",
    "pakistan":"PK","panama":"PA","papua new guinea":"PG","paraguay":"PY","peru":"PE",
    "philippines":"PH","poland":"PL","portugal":"PT","qatar":"QA","romania":"RO",
    "russia":"RU","rwanda":"RW","saudi arabia":"SA","senegal":"SN","serbia":"RS",
    "sierra leone":"SL","singapore":"SG","slovakia":"SK","slovenia":"SI",
    "somalia":"SO","south africa":"ZA","south korea":"KR","south sudan":"SS",
    "spain":"ES","sri lanka":"LK","sudan":"SD","sweden":"SE","switzerland":"CH",
    "syria":"SY","taiwan":"TW","tajikistan":"TJ","tanzania":"TZ","thailand":"TH",
    "togo":"TG","tunisia":"TN","turkey":"TR","turkmenistan":"TM","uganda":"UG",
    "ukraine":"UA","united arab emirates":"AE","uae":"AE",
    "united kingdom":"GB","uk":"GB","united states":"US","usa":"US","us":"US",
    "uruguay":"UY","uzbekistan":"UZ","venezuela":"VE","vietnam":"VN","yemen":"YE",
    "zambia":"ZM","zimbabwe":"ZW",
    "central african republic":"CF","congo dr":"CD","democratic republic of congo":"CD",
    "equatorial guinea":"GQ","eritrea":"ER","eswatini":"SZ","fiji":"FJ",
    "guinea-bissau":"GW","lesotho":"LS","liechtenstein":"LI","macau":"MO",
    "monaco":"MC","san marino":"SM","seychelles":"SC","timor-leste":"TL",
}

LANG_NAMES = {
    "en": "English", "fr": "French", "ar": "Arabic", "es": "Spanish",
    "pt": "Portuguese", "ru": "Russian", "de": "German", "it": "Italian",
    "tr": "Turkish", "id": "Indonesian", "ms": "Malay", "bn": "Bangla",
    "hi": "Hindi", "ur": "Urdu", "fa": "Persian", "sw": "Swahili",
    "ha": "Hausa", "yo": "Yoruba", "am": "Amharic", "so": "Somali",
    "vi": "Vietnamese", "th": "Thai", "zh-cn": "Chinese", "ko": "Korean",
    "ja": "Japanese", "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian",
    "ro": "Romanian", "hu": "Hungarian", "cs": "Czech", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "el": "Greek",
    "he": "Hebrew", "tl": "Filipino", "kn": "Kannada", "ml": "Malayalam",
    "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "mr": "Marathi",
    "si": "Sinhala", "km": "Khmer", "lo": "Lao", "my": "Burmese",
    "ka": "Georgian", "az": "Azerbaijani", "kk": "Kazakh", "ky": "Kyrgyz",
    "uz": "Uzbek", "tk": "Turkmen", "tg": "Tajik", "mn": "Mongolian",
    "ne": "Nepali", "pa": "Punjabi", "af": "Afrikaans", "sq": "Albanian",
    "hy": "Armenian", "be": "Belarusian", "bs": "Bosnian", "bg": "Bulgarian",
    "hr": "Croatian", "et": "Estonian", "gl": "Galician", "lv": "Latvian",
    "lt": "Lithuanian", "mk": "Macedonian", "sk": "Slovak", "sl": "Slovenian",
    "sr": "Serbian", "cy": "Welsh", "eu": "Basque", "ca": "Catalan",
}

def detect_language(text):
    if not text or len(text.strip()) < 5:
        return None
    if not LANGDETECT_OK:
        return None
    try:
        lang_code = _langdetect(text)
        return LANG_NAMES.get(lang_code, lang_code.title())
    except Exception:
        return None

def country_to_flag(country_name):
    key = (country_name or "").strip().lower()
    iso = COUNTRY_TO_ISO.get(key)
    if not iso:
        return "🌍"
    return "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in iso)

def lookup_range_info(service, number):
    rd = load_ranges()
    entries = rd.get(service, [])
    clean = re.sub(r'\D', '', str(number))
    best = None
    for e in entries:
        prefix = re.sub(r'[Xx]+$', '', e.get("range", ""))
        prefix = re.sub(r'\D', '', prefix)
        if prefix and clean.startswith(prefix):
            if best is None or len(prefix) > len(re.sub(r'[Xx]+$', '', re.sub(r'\D', '', best.get("range", "")))):
                best = e
    return best

def send_sync(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        payload = {"chat_id": str(chat_id), "text": text}
        if parse_mode:   payload["parse_mode"] = parse_mode
        if reply_markup: payload["reply_markup"] = reply_markup
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=10)
        res = r.json()
        if res.get("error_code") == 429:
            time.sleep(res.get("parameters", {}).get("retry_after", 5) + 1)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"❌ send_sync: {e}")

SERVICE_SHORT = {
    "facebook":  "FB",
    "instagram": "IG",
    "whatsapp":  "WS",
    "telegram":  "TG",
}

def build_otp_msg(service, flag, number, lang=None):
    sid        = SERVICE_SHORT.get(str(service).lower(), str(service)[:2].upper())
    emoji      = SERVICES.get(str(service).title(), "📱")
    masked_num = mask_number(number)
    msg        = f"{flag} #{sid} {emoji} • {masked_num}"
    if lang:
        msg += f" • {lang}"
    return msg

def build_otp_display(otp):
    s = str(otp)
    if len(s) == 6:
        return f"{s[:3]}-{s[3:]}"
    return s

def group_markup(otp):
    return {
        "inline_keyboard": [
            [{
                "text": f"🔑 {build_otp_display(otp)}",
                "copy_text": {"text": str(otp)},
                "style": "danger",
            }],
            [
                {"text": "📞 GET NUMBER",   "url": GET_NUMBER_LINK,      "style": "primary"},
                {"text": "📢 MAIN CHANNEL", "url": COMMUNITY_GROUP_LINK, "style": "success"},
            ]
        ]
    }

def user_markup(otp):
    return {
        "inline_keyboard": [[{
            "text": f"🔑 {build_otp_display(otp)}",
            "copy_text": {"text": str(otp)},
            "style": "danger",
        }]]
    }

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📞 Get Number", style="success"),
         KeyboardButton("💰 My Balance", style="primary")],
        [KeyboardButton("📊 Status",     style="primary"),
         KeyboardButton("💸 Withdraw",   style="danger")],
        [KeyboardButton("ℹ️ Help",       style="success")],
    ], resize_keyboard=True)

def admin_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Add Range",    style="success"),
         KeyboardButton("📋 List Ranges", style="primary")],
        [KeyboardButton("❌ Delete Range", style="danger"),
         KeyboardButton("🔙 Back")],
        [KeyboardButton("👤 Add Admin",    style="primary"),
         KeyboardButton("🗑 Remove Admin", style="danger")],
        [KeyboardButton("👥 Admin List",   style="primary")],
    ], resize_keyboard=True)

def service_kb(ranges_data):
    buttons = []
    for svc, emoji in SERVICES.items():
        has   = svc in ranges_data and len(ranges_data[svc]) > 0
        label = f"{emoji} {svc}" + ("" if has else " ⚠️")
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"svc:{svc}",
            style="success" if has else "danger",
        )])
    return InlineKeyboardMarkup(buttons)

def country_kb(service, ranges_data):
    entries = ranges_data.get(service, [])
    buttons = []
    for i, e in enumerate(entries):
        flag  = e.get("flag", "🌍")
        label = f"{flag} {e['country']}"
        buttons.append([InlineKeyboardButton(
            label, callback_data=f"num:{service}:{i}", style="success",
        )])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back", style="danger")])
    return InlineKeyboardMarkup(buttons)

def numbers_kb(session_id, numbers, flag):
    buttons = []
    for n in numbers:
        buttons.append([InlineKeyboardButton(
            f"{flag} {n}",
            copy_text=CopyTextButton(text=n),
            style="success",
        )])
    buttons.append([
        InlineKeyboardButton("🔄 CHANGE",  callback_data=f"change:{session_id}", style="danger"),
        InlineKeyboardButton("📨 VIEW OTP", url=OTP_GROUP_LINK,                  style="primary"),
    ])
    return InlineKeyboardMarkup(buttons)

def numbers_header(service, flag, country):
    return (
        f"{flag} <b>{country} Allocated</b> {SERVICES.get(service, '📱')} {service}\n\n"
        f"⏳ Waiting for OTP....."
    )

watch_sessions = {}

def poll_session(session_id):
    sess = watch_sessions.get(session_id)
    if not sess:
        return

    start = time.time()
    sent  = set()
    clean_numbers = {re.sub(r'\D', '', n) for n in sess["numbers"]}
    logger.info(f"🔍 Watching {session_id}: {sess['numbers']} [{sess['service']}/{sess['panel']}]")

    while time.time() - start < 600:
        sess = watch_sessions.get(session_id)
        if not sess or not sess.get("active"):
            return

        try:
            otps = fastx_get_otps() if sess["panel"] == "FastX" else stex_get_otps()
            for item in otps:
                num = re.sub(r'\D', '', str(item.get("number", "")))
                if num not in clean_numbers:
                    continue

                msg_text = item.get("message", "") or item.get("sms", "")
                otp = None
                raw = item.get("otp", "")
                if raw:
                    digits = re.sub(r'\D', '', raw)
                    if len(digits) >= 4:
                        otp = digits
                if not otp:
                    m2 = OTP_PATTERN.search(re.sub(r'(\d+)\s(\d+)', r'\1\2', msg_text)) or OTP_PATTERN.search(msg_text)
                    if not m2:
                        continue
                    otp = m2.group(1)

                key = f"{num}:{otp}:{msg_text}"
                if key in sent:
                    continue
                sent.add(key)

                full_number = next((n for n in sess["numbers"] if re.sub(r'\D', '', n) == num), num)
                lang    = detect_language(msg_text)
                top_msg = build_otp_msg(sess["service"], sess["flag"], full_number, lang)

                send_sync(sess["user_chat_id"], top_msg, reply_markup=user_markup(otp))
                if str(sess["user_chat_id"]) != str(ADMIN_CHAT_ID):
                    send_sync(ADMIN_CHAT_ID, top_msg, reply_markup=user_markup(otp))
                send_sync(OTP_GROUP_ID, top_msg, reply_markup=group_markup(otp))

                logger.info(f"✅ OTP {otp} → {full_number} → Group")

            time.sleep(3)
        except Exception as e:
            logger.error(f"❌ poll error ({session_id}): {e}")
            time.sleep(3)

    logger.info(f"⌛ Session {session_id} timed out")

ALLOWED_SIDS = {"facebook", "instagram", "whatsapp", "telegram"}

def group_forwarder_loop():
    logger.info("🚀 Group forwarder started!")
    while True:
        try:
            hits = []
            for h in fastx_get_console(): hits.append({**h, "panel": "FastX"})
            for h in stex_get_console():  hits.append({**h, "panel": "Stex"})
            logger.info(f"Group scan: {len(hits)} hits")

            for hit in hits:
                msg_text = hit.get("message", "")
                otp      = hit.get("otp", "")

                if not otp:
                    m = OTP_PATTERN.search(msg_text)
                    if not m:
                        continue
                    otp = m.group(1)

                number  = hit.get("number", "") or hit.get("range", "")
                service = hit.get("sid", "Unknown")

                if service.lower() not in ALLOWED_SIDS:
                    continue

                key = f"{number}:{otp}:{msg_text}"
                if key in group_sent_otps:
                    continue
                group_sent_otps.add(key)

                masked = mask_number(number) if number else "Unknown"
                info   = lookup_range_info(service.title(), number) or {}
                flag   = info.get("flag", "🌍")
                lang   = detect_language(msg_text)

                top_msg = build_otp_msg(service, flag, masked, lang)
                send_sync(OTP_GROUP_ID, top_msg, reply_markup=group_markup(otp))
                logger.info(f"✅ Group OTP {otp} → {masked} ({service})")
                time.sleep(1.2)

            if len(group_sent_otps) > 2000:
                group_sent_otps.clear()
            time.sleep(5)

        except Exception as e:
            logger.error(f"❌ Group forwarder: {e}")
            time.sleep(5)

admin_state = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"Welcome To NOX SMS, {name}!\nYour Bot is active now.",
        reply_markup=main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text    = (update.message.text or "").strip()

    if chat_id in admin_state and is_admin(chat_id):
        state = admin_state[chat_id]

        if state["step"] == "wait_service":
            svc = next((s for s in SERVICES if s.lower() == text.lower()), None)
            if not svc:
                await update.message.reply_text("❌ Unknown service. Choose:\n" + "\n".join(SERVICES.keys()))
                return
            state["data"]["service"] = svc
            state["step"] = "wait_panel"
            await update.message.reply_text(
                "2️⃣ Panel name?\n\nReply: FastX  or  Stex",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("FastX", style="success"), KeyboardButton("Stex", style="primary")]],
                    resize_keyboard=True
                )
            )
            return

        if state["step"] == "wait_panel":
            panel = next((p for p in PANELS if p.lower() == text.lower()), None)
            if not panel:
                await update.message.reply_text("❌ Choose: FastX  or  Stex")
                return
            state["data"]["panel"] = panel
            state["step"] = "wait_country"
            await update.message.reply_text("3️⃣ Country name?\n\nExample: Bangladesh", reply_markup=admin_keyboard())
            return

        if state["step"] == "wait_country":
            state["data"]["country"] = text
            state["step"] = "wait_range"
            await update.message.reply_text(
                "4️⃣ Range number?\n\nExample: 880177XXX\n(Add XXX at the end for wildcards)",
                reply_markup=admin_keyboard()
            )
            return

        if state["step"] == "wait_new_admin":
            new_id = text.strip()
            if not new_id.lstrip("-").isdigit():
                await update.message.reply_text("❌ Valid Telegram User ID দিন (শুধু সংখ্যা)।\nExample: 123456789")
                return
            if new_id == str(ADMIN_CHAT_ID):
                await update.message.reply_text("⚠️ আপনি নিজেই Owner!")
                del admin_state[chat_id]
                return
            if add_admin(new_id):
                del admin_state[chat_id]
                await update.message.reply_text(f"✅ Admin যোগ হয়েছে!\n\n👤 User ID: {new_id}", reply_markup=admin_keyboard())
            else:
                del admin_state[chat_id]
                await update.message.reply_text(f"⚠️ {new_id} already admin আছে।", reply_markup=admin_keyboard())
            return

        if state["step"] == "wait_range":
            rng = text.strip()
            d   = state["data"]
            flag = country_to_flag(d["country"])
            ranges_data = load_ranges()
            ranges_data.setdefault(d["service"], []).append({
                "panel": d["panel"], "country": d["country"], "flag": flag, "range": rng,
            })
            save_ranges(ranges_data)
            del admin_state[chat_id]
            await update.message.reply_text(
                f"✅ Range added!\n\n📱 Service: {d['service']}\n🌐 Panel: {d['panel']}\n{flag} Country: {d['country']}\n🔢 Range: {rng}",
                reply_markup=admin_keyboard()
            )
            return

    if text == "📞 Get Number":
        rd = load_ranges()
        await update.message.reply_text("📱 Select a Service:", reply_markup=service_kb(rd))

    elif text == "💰 My Balance":
        await update.message.reply_text("💰 My Balance\n\n✅ Status: Running", reply_markup=main_keyboard())

    elif text == "📊 Status":
        rd = load_ranges()
        svc_list = "\n".join([f"  {SERVICES[s]} {s}: {len(v)} ranges" for s, v in rd.items()]) or "  None"
        await update.message.reply_text(
            f"📊 Bot Status\n\n✅ Running\n🌐 FastX + Stex connected\n\n📋 Ranges:\n{svc_list}",
            reply_markup=main_keyboard()
        )

    elif text == "💸 Withdraw":
        await update.message.reply_text("💸 Not configured yet.", reply_markup=main_keyboard())

    elif text == "ℹ️ Help":
        await update.message.reply_text(
            "ℹ️ Help\n\n1️⃣ Click Get Number\n2️⃣ Pick service\n3️⃣ Pick country\n4️⃣ OTP auto-forwarded!\n\nAdmin: /admin",
            reply_markup=main_keyboard()
        )

    elif text == "➕ Add Range" and is_admin(chat_id):
        admin_state[chat_id] = {"step": "wait_service", "data": {}}
        await update.message.reply_text(
            "➕ Add Range — Step 1/4\n\n1️⃣ Service name?\n\nFacebook / Instagram / WhatsApp / Telegram",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(s) for s in list(SERVICES.keys())[:2]],
                 [KeyboardButton(s) for s in list(SERVICES.keys())[2:]]],
                resize_keyboard=True
            )
        )

    elif text == "📋 List Ranges" and is_admin(chat_id):
        rd = load_ranges()
        if not rd:
            await update.message.reply_text("No ranges yet.", reply_markup=admin_keyboard())
            return
        lines = []
        for svc, entries in rd.items():
            lines.append(f"\n{SERVICES[svc]} {svc}:")
            for i, e in enumerate(entries):
                lines.append(f"  {i}. {e.get('flag','🌍')} {e['country']} | {e['panel']} | {e['range']}")
        await update.message.reply_text("📋 All Ranges:\n" + "\n".join(lines), reply_markup=admin_keyboard())

    elif text == "❌ Delete Range" and is_admin(chat_id):
        rd = load_ranges()
        if not rd:
            await update.message.reply_text("No ranges to delete.", reply_markup=admin_keyboard())
            return
        buttons = []
        for svc, entries in rd.items():
            for i, e in enumerate(entries):
                label = f"{SERVICES[svc]} {svc} | {e.get('flag','🌍')} {e['country']} | {e['range']}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"del:{svc}:{i}", style="danger")])
        await update.message.reply_text("❌ Choose range to delete:", reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "👤 Add Admin" and is_owner(chat_id):
        admin_state[chat_id] = {"step": "wait_new_admin", "data": {}}
        await update.message.reply_text(
            "👤 Add Admin\n\nনতুন Admin এর Telegram User ID পাঠান।\n(ID জানতে @userinfobot এ /start দিন)",
            reply_markup=admin_keyboard()
        )

    elif text == "🗑 Remove Admin" and is_owner(chat_id):
        admins = load_admins()
        if not admins:
            await update.message.reply_text("⚠️ কোনো extra admin নেই।", reply_markup=admin_keyboard())
            return
        buttons = [[InlineKeyboardButton(f"🗑 {cid}", callback_data=f"removeadmin:{cid}", style="danger")] for cid in admins]
        await update.message.reply_text("🗑 কোন admin কে remove করবেন?", reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "👥 Admin List" and is_owner(chat_id):
        admins = load_admins()
        lines  = [f"👑 Owner: {ADMIN_CHAT_ID} (আপনি)"]
        if admins:
            lines += ["", "👤 Extra Admins:"] + [f"  {i+1}. {cid}" for i, cid in enumerate(admins)]
        else:
            lines.append("\n⚠️ কোনো extra admin নেই।")
        await update.message.reply_text("\n".join(lines), reply_markup=admin_keyboard())

    elif text == "🔙 Back":
        admin_state.pop(chat_id, None)
        await update.message.reply_text("👈 Back to main menu.", reply_markup=main_keyboard())

    elif text in ("/admin", "⚙️ Admin"):
        if not is_admin(chat_id):
            await update.message.reply_text("❌ Admin only.")
            return
        await update.message.reply_text("⚙️ Admin Panel", reply_markup=admin_keyboard())

async def fetch_and_show_numbers(query, service, entry, edit=True):
    target_text = "⏳ Getting your numbers, please wait..."
    if edit:
        await query.edit_message_text(target_text)
    else:
        await query.message.reply_text(target_text)

    result = [None]
    def fetch():
        result[0] = get_numbers_batch(entry["panel"], entry["range"], NUMBERS_PER_BATCH)
    t = threading.Thread(target=fetch)
    t.start()
    t.join(timeout=30)

    numbers_data = result[0] or []
    if not numbers_data:
        txt = "⚠️ Out of stock for this range.\nTry another country."
        if edit:
            await query.edit_message_text(txt)
        return

    numbers      = [n["number"] for n in numbers_data]
    country      = numbers_data[0].get("country", entry["country"])
    flag         = entry.get("flag", "🌍")
    service_name = entry.get("_service")

    session_id = uuid.uuid4().hex[:10]
    watch_sessions[session_id] = {
        "numbers":      numbers,
        "panel":        entry["panel"],
        "service":      service_name,
        "country":      country,
        "flag":         flag,
        "user_chat_id": query.message.chat.id,
        "active":       True,
    }

    header = numbers_header(service_name, flag, country)
    markup = numbers_kb(session_id, numbers, flag)

    if edit:
        await query.edit_message_text(header, parse_mode="HTML", reply_markup=markup)
    else:
        await query.message.reply_text(header, parse_mode="HTML", reply_markup=markup)

    threading.Thread(target=poll_session, args=(session_id,), daemon=True).start()

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    if data == "back":
        await query.answer()
        rd = load_ranges()
        await query.edit_message_text("📱 Select a Service:", reply_markup=service_kb(rd))
        return

    if data.startswith("svc:"):
        await query.answer()
        svc = data[4:]
        rd  = load_ranges()
        entries = rd.get(svc, [])
        if not entries:
            await query.edit_message_text(
                f"⚠️ No ranges for {svc} yet.\nAdmin needs to add ranges first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back", style="danger")]])
            )
            return
        await query.edit_message_text(f"{SERVICES[svc]} {svc} — Select a country:", reply_markup=country_kb(svc, rd))
        return

    if data.startswith("num:"):
        await query.answer()
        _, svc, idx_str = data.split(":", 2)
        idx     = int(idx_str)
        rd      = load_ranges()
        entries = rd.get(svc, [])
        if idx >= len(entries):
            await query.edit_message_text("⚠️ Range not found.")
            return
        entry = dict(entries[idx])
        entry["_service"] = svc
        await fetch_and_show_numbers(query, svc, entry, edit=True)
        return

    if data.startswith("change:"):
        await query.answer("Getting new numbers...")
        session_id = data.split(":", 1)[1]
        old = watch_sessions.get(session_id)
        if not old:
            await query.edit_message_text("⚠️ Session expired. Please use 📞 Get Number again.")
            return
        old["active"] = False
        rd      = load_ranges()
        entries = rd.get(old["service"], [])
        entry   = next((e for e in entries if e["panel"] == old["panel"]), None)
        if not entry:
            await query.edit_message_text("⚠️ Range no longer available.")
            return
        entry = dict(entry)
        entry["_service"] = old["service"]
        await fetch_and_show_numbers(query, old["service"], entry, edit=True)
        return

    if data.startswith("removeadmin:"):
        await query.answer()
        if not is_owner(query.message.chat.id):
            await query.answer("❌ শুধু Owner পারবে!", show_alert=True)
            return
        target_id = data.split(":", 1)[1]
        if remove_admin(target_id):
            await query.edit_message_text(f"✅ Admin remove হয়েছে!\n\n🗑 User ID: {target_id}")
        else:
            await query.edit_message_text(f"⚠️ {target_id} admin list এ নেই।")
        return

    if data.startswith("del:"):
        await query.answer()
        _, svc, idx_str = data.split(":", 2)
        idx = int(idx_str)
        rd  = load_ranges()
        if svc in rd and idx < len(rd[svc]):
            removed = rd[svc].pop(idx)
            if not rd[svc]:
                del rd[svc]
            save_ranges(rd)
            await query.edit_message_text(f"✅ Deleted:\n{svc} | {removed['country']} | {removed['range']}")
        else:
            await query.edit_message_text("❌ Not found.")
        return

    await query.answer()

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Bot running!\n🌐 FastX + Stex connected.", reply_markup=main_keyboard())

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(str(update.effective_chat.id)):
        await update.message.reply_text("❌ Admin only.")
        return
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=admin_keyboard())

def main():
    threading.Thread(target=group_forwarder_loop, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("admin",  admin_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 NOX SMS Bot running!")
    app.run_polling(drop_pending_updates=True, allowed_updates=['message', 'callback_query'])

if __name__ == "__main__":
    main()
