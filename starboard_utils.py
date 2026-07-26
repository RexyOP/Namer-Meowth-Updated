"""Starboard utility functions"""
import csv
import os
from typing import Optional
from config import STARBOARD_DATA_PATH, Emojis

# Pokemon that have different male/female sprites
GENDER_DIFFERENCE_POKEMON = {
    "Hisuian Sneasel", "Basculegion", "Butterfree", "Kricketune", "Hippopotas",
    "Oinkologne", "Vileplume", "Sudowoodo", "Wobbuffet", "Girafarig", "Heracross",
    "Piloswine", "Octillery", "Combusken", "Beautifly", "Relicanth", "Staraptor",
    "Kricketot", "Pachirisu", "Hippowdon", "Toxicroak", "Abomasnow", "Rhyperior",
    "Tangrowth", "Mamoswine", "Jellicent", "Venusaur", "Raticate", "Alakazam",
    "Magikarp", "Gyarados", "Meganium", "Politoed", "Quagsire", "Ursaring",
    "Houndoom", "Blaziken", "Ludicolo", "Meditite", "Medicham", "Camerupt",
    "Cacturne", "Staravia", "Roserade", "Floatzel", "Garchomp", "Croagunk",
    "Lumineon", "Unfezant", "Frillish", "Meowstic", "Indeedee", "Rattata",
    "Pikachu", "Kadabra", "Rhyhorn", "Goldeen", "Seaking", "Scyther", "Murkrow",
    "Steelix", "Sneasel", "Donphan", "Torchic", "Nuzleaf", "Shiftry", "Roselia",
    "Milotic", "Bibarel", "Ambipom", "Finneon", "Weavile", "Raichu", "Golbat",
    "Dodrio", "Rhydon", "Ledyba", "Ledian", "Wooper", "Gligar", "Scizor",
    "Dustox", "Gulpin", "Swalot", "Starly", "Bidoof", "Luxray", "Combee",
    "Buizel", "Gabite", "Snover", "Pyroar", "Zubat", "Gloom", "Doduo", "Hypno",
    "Eevee", "Aipom", "Numel", "Shinx", "Luxio", "Gible", "Xatu", "Proud Amsterdammer Pyroar"
}

def load_cdn_mapping() -> dict:
    """Load Pokemon CDN number mapping from CSV file"""
    mapping = {}
    try:
        csv_path = os.path.join(os.path.dirname(STARBOARD_DATA_PATH), 'pokemon_cdn_mapping.csv')
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                mapping[row['name'].strip().lower()] = row['cdn_number'].strip()
    except Exception as e:
        print(f"Error loading CDN mapping: {e}")
    return mapping

def get_gender_emoji(gender: Optional[str]) -> str:
    """Get gender emoji based on gender"""
    if gender == 'male':
        return Emojis.MALE
    elif gender == 'female':
        return Emojis.FEMALE
    elif gender == 'unknown':
        return Emojis.UNKNOWN
    else:
        return ""

def find_pokemon_image_url(pokemon_name: str, is_shiny: bool = False, gender: Optional[str] = None, is_gigantamax: bool = False) -> Optional[str]:
    """Find Pokemon image URL using CDN mapping CSV"""
    cdn_mapping = load_cdn_mapping()
    normalized_name = pokemon_name.strip().lower()

    # Build the lookup name
    if is_gigantamax:
        # Eternatus with Gigantamax factor is Eternamax Eternatus in the CDN
        if normalized_name == "eternatus":
            lookup_name = "eternamax eternatus"
        else:
            lookup_name = f"gigantamax {normalized_name}"
    else:
        lookup_name = normalized_name

    cdn_number = cdn_mapping.get(lookup_name)

    if cdn_number is None:
        print(f"DEBUG: No CDN number found for '{lookup_name}'")
        return None

    # Gigantamax/Eternamax forms have no gender difference sprites
    if is_gigantamax:
        suffix = cdn_number
    else:
        use_female_sprite = (
            gender == 'female'
            and pokemon_name.strip() in GENDER_DIFFERENCE_POKEMON
        )
        suffix = f"{cdn_number}F" if use_female_sprite else cdn_number

    if is_shiny:
        return f"https://cdn.poketwo.net/shiny/{suffix}.png"
    else:
        return f"https://cdn.poketwo.net/images/{suffix}.png"

def format_iv_display(iv) -> str:
    """Format IV for display"""
    if iv == "Hidden":
        return "Hidden"
    elif iv == "???":
        return "???"
    else:
        return f"{iv}%"

def create_jump_button_view(message) -> Optional:
    """Create a view with jump to message button"""
    if not message:
        return None

    import discord
    view = discord.ui.View()
    jump_button = discord.ui.Button(
        label="Jump to Message",
        url=message.jump_url,
        emoji="🔗",
        style=discord.ButtonStyle.link
    )
    view.add_item(jump_button)
    return view
