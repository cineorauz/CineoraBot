import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
CHANNELS = [c.strip() for c in os.getenv("CHANNELS", "").split(",") if c.strip()]
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "")
# O'zbekcha tarjima (Tilmoch/Sayqalchi): developer.tahrirchi.uz → Kalitlar
TAHRIRCHI_API_KEY = os.getenv("TAHRIRCHI_API_KEY", "")
# Click/Payme orqali to'lov uchun (BotFather → Payments). Bo'sh bo'lsa bu usul yashirin turadi
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
PORT = int(os.getenv("PORT", "10000"))
