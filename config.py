"""Bot configuration and constants"""
import os

# Discord Configurationn
TOKEN = os.getenv("DISCORD_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Optional: for private model repos
BOT_PREFIX = ['c!', 'C!','zoro ', 'Zoro ','Rexy ', 'rexy ','zoro', 'Zoro','Rexy', 'rexy']
POKETWO_USER_ID = 716390085896962058

# Embed Configuration
EMBED_COLOR = 0xf4e5ba

# Custom Emojis
class Emojis:
    GREEN_DOT = "<:greendot:1531554496638095410>"
    GREY_DOT = "<:greydot:1531554666071068805>"
    MALE = "<:male_male:1531555055529099288>"
    FEMALE = "<:female:1531555113385328801>"
    UNKNOWN = "<:unknown:1531555497335980082>"
    GIGANTAMAX = "<:gigantamax:1531555227629649951>"
    EGG = "<:egg:1531557304615571467>"
    MISSINGNO = "<:missingno:1531555670321664000>"
    GIFTBOX = "<:giftbox:1531556024295755876>"
    ANIMATED_GIFTBOX = "<a:animatedgiftbox:1531556196363010159>"

# Cache Configuration
CACHE_TTL = 60  # seconds
CACHE_TTL_SETTINGS = 300  # 5 minutes

# Collection Configuration
ITEMS_PER_PAGE = 20
MAX_DISPLAY_ITEMS = 150

# IV Thresholds
HIGH_IV_THRESHOLD = 90.0
LOW_IV_THRESHOLD = 10.0
PREDICTION_CONFIDENCE = 90.0

# Database Configuration
DB_TIMEOUT_MS = 3000
DB_MAX_POOL_SIZE = 10
DB_MIN_POOL_SIZE = 1

# File Paths
POKEMON_DATA_PATH = "data/pokemondata.json"
STARBOARD_DATA_PATH = "data/starboard.txt"

# Model Configuration (for predict.py)
MODEL_CACHE_DIR = "model_cache"
