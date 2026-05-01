"""Utility functions for Pokemon operations"""
import json
import unicodedata
import discord
from typing import List, Optional, Dict
from config import POKEMON_DATA_PATH

EVENT_DATA_PATH = "data/eventdata.json"

def load_pokemon_data() -> List[Dict]:
    """Load Pokemon data from pokemondata.json, with eventdata.json merged in.

    Event pokemon are appended after regular pokemon so that regular entries
    always take priority in searches (first-match wins).
    """
    data = []

    try:
        with open(POKEMON_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to load pokemondata.json: {e}")

    try:
        with open(EVENT_DATA_PATH, 'r', encoding='utf-8') as f:
            event_data = json.load(f)
        data = data + event_data
        print(f"[DATA] Loaded {len(event_data)} event Pokemon from eventdata.json")
    except Exception as e:
        print(f"[DATA] Could not load eventdata.json (non-fatal): {e}")

    return data

def normalize_pokemon_name(name: str) -> str:
    """
    Normalize Pokemon name by:
    1. Removing accents/diacritics
    2. Removing gender suffixes (-Male, -Female)
    """
    if not name:
        return ""

    # Remove accents/diacritics
    normalized = unicodedata.normalize('NFD', name)
    without_accents = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')

    # Remove gender suffixes
    if without_accents.endswith("-Male"):
        without_accents = without_accents[:-5]
    elif without_accents.endswith("-Female"):
        without_accents = without_accents[:-7]

    return without_accents.strip()

def find_pokemon_by_name(name: str, pokemon_data: List[Dict]) -> Optional[Dict]:
    """Find Pokemon by exact name match"""
    if not name or not pokemon_data:
        return None

    name_lower = name.lower().strip()

    for pokemon in pokemon_data:
        # Check main name
        if pokemon.get('name', '').lower() == name_lower:
            return pokemon

        # Check other language names
        other_names = pokemon.get('other_names')
        if other_names and isinstance(other_names, dict):
            for lang_name_data in other_names.values():
                if isinstance(lang_name_data, str):
                    if lang_name_data.lower() == name_lower:
                        return pokemon
                elif isinstance(lang_name_data, list):
                    for lang_name in lang_name_data:
                        if lang_name and isinstance(lang_name, str) and lang_name.lower() == name_lower:
                            return pokemon
    return None

def find_pokemon_by_name_flexible(search_name: str, pokemon_data: List[Dict]) -> Optional[Dict]:
    """Find Pokemon with flexible matching (accent-insensitive)"""
    if not search_name or not pokemon_data:
        return None

    normalized_search = normalize_pokemon_name(search_name).lower()

    for pokemon in pokemon_data:
        # Check main name
        if normalize_pokemon_name(pokemon.get('name', '')).lower() == normalized_search:
            return pokemon

        # Check other language names
        other_names = pokemon.get('other_names')
        if other_names and isinstance(other_names, dict):
            for lang_name_data in other_names.values():
                if isinstance(lang_name_data, str):
                    if normalize_pokemon_name(lang_name_data).lower() == normalized_search:
                        return pokemon
                elif isinstance(lang_name_data, list):
                    for lang_name in lang_name_data:
                        if lang_name and isinstance(lang_name, str):
                            if normalize_pokemon_name(lang_name).lower() == normalized_search:
                                return pokemon
    return None

def get_pokemon_with_variants(pokemon_name: str, pokemon_data: List[Dict]) -> List[str]:
    """
    Get Pokemon and all its variants

    Example:
        "Furfrou" -> ["Furfrou", "Pharaoh Trim Furfrou", "Debutante Trim Furfrou", ...]
    """
    base_pokemon = find_pokemon_by_name_flexible(pokemon_name, pokemon_data)
    if not base_pokemon:
        return []

    base_name = base_pokemon['name']
    variants = [base_name]

    # Find all variants of this Pokemon
    for pokemon in pokemon_data:
        if (pokemon.get('is_variant') and 
            pokemon.get('variant_of', '').lower() == base_name.lower()):
            variants.append(pokemon['name'])

    return variants

def is_rare_pokemon(pokemon: Dict) -> bool:
    """Check if Pokemon is Legendary, Mythical, or Ultra Beast"""
    if not pokemon:
        return False

    rarity = pokemon.get('rarity', '')

    # Handle both string and list
    if isinstance(rarity, list):
        return any(r.lower() in ['legendary', 'mythical', 'ultra beast'] for r in rarity)
    else:
        return rarity.lower() in ['legendary', 'mythical', 'ultra beast']

def format_pokemon_prediction(name: str, confidence: str) -> str:
    """Format the Pokemon prediction output"""
    if name.endswith("-Male") or name.endswith("-Female"):
        if name.endswith("-Male"):
            base_name = name[:-5]
            gender = "Male"
        else:
            base_name = name[:-7]
            gender = "Female"
        return f"{base_name}: {confidence}\nGender: {gender}"
    else:
        return f"{name}: {confidence}"

async def get_image_url_from_message(message: discord.Message) -> Optional[str]:
    """Extract image URL from message attachments or embeds"""
    # Check attachments first
    if message.attachments:
        for attachment in message.attachments:
            if any(attachment.url.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
                return attachment.url

    # Check embeds
    if message.embeds:
        embed = message.embeds[0]
        if embed.image and embed.image.url:
            return embed.image.url
        elif embed.thumbnail and embed.thumbnail.url:
            return embed.thumbnail.url

    return None

def create_text_file(content: str, filename: str = "collection.txt") -> discord.File:
    """Create a text file from string content"""
    import io
    file_content = io.BytesIO(content.encode('utf-8'))
    return discord.File(file_content, filename=filename)
