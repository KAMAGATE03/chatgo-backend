#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Backend API pour Annuaire CI - Chat&Go
Version : 5.9 - Correction complète et robuste des erreurs de type (NaN/float -> str)
"""

import os
import re
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
import pandas as pd
import uvicorn
import requests
from dotenv import load_dotenv

load_dotenv()

CSV_FILE = os.environ.get("CHATGO_CSV_FILE", "annuaire_complet.csv")
SEPARATOR = ";"
ENCODING = "utf-8"  # Essayez "latin-1" si erreur d'encodage

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PORT = int(os.environ.get("PORT", 8000))


# Stop words
STOP_WORDS = {
    'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
    'me', 'te', 'se', 'le', 'la', 'les', 'un', 'une', 'des',
    'pour', 'par', 'avec', 'sans', 'chez', 'sur', 'sous', 'dans',
    'de', 'du', 'au', 'aux', 'à', 'vers', 'en', 'entre',
    'et', 'ou', 'ni', 'mais', 'donc', 'car', 'or',
    'qui', 'que', 'quoi', 'dont', 'où',
    'est', 'sont', 'suis', 'es', 'sommes', 'êtes',
    'cherche', 'cherches', 'cherchons', 'cherchez', 'cherchent',
    'trouve', 'trouves', 'trouvons', 'trouvez', 'trouvent',
    'veux', 'veut', 'voulons', 'voulez', 'veulent',
    'ce', 'cet', 'cette', 'ces', 'mon', 'ton', 'son',
    'ma', 'ta', 'sa', 'mes', 'tes', 'ses'
}

# Valeur par défaut pour les images manquantes
DEFAULT_IMAGE = "https://via.placeholder.com/512x320?text=No+Image"


def safe_str(value) -> str:
    """
    Convertit n'importe quelle valeur (float, NaN, None, int...) en chaîne
    propre et sans espace superflu. Utilisé partout où une valeur issue
    du CSV/pandas est manipulée comme du texte.
    """
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def safe_float(value) -> Optional[float]:
    """Convertit une valeur en float, ou None si impossible/NaN/vide."""
    if value is None or value == '':
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def safe_int(value) -> Optional[int]:
    """Convertit une valeur en int, ou None si impossible/NaN/vide."""
    f = safe_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except (ValueError, TypeError):
        return None


class Entreprise:
    def __init__(self, data: Dict):
        self.company_id = safe_str(data.get('company_id', ''))
        self.company_name = safe_str(data.get('company_name', ''))
        self.category = safe_str(data.get('category', ''))
        self.description = safe_str(data.get('description', ''))
        self.city = safe_str(data.get('city', ''))
        self.district = safe_str(data.get('district', ''))
        self.address = safe_str(data.get('address', ''))
        self.latitude = safe_str(data.get('latitude', ''))
        self.longitude = safe_str(data.get('longitude', ''))
        self.phone = safe_str(data.get('phone', ''))
        self.phone_link = safe_str(data.get('phone_link', ''))
        self.whatsapp = safe_str(data.get('whatsapp', ''))
        self.whatsapp_link = safe_str(data.get('whatsapp_link', ''))
        self.email = safe_str(data.get('email', ''))
        self.email_link = safe_str(data.get('email_link', ''))
        self.website = safe_str(data.get('website', ''))
        self.facebook = safe_str(data.get('facebook', ''))
        self.instagram = safe_str(data.get('instagram', ''))
        self.logo_url = safe_str(data.get('logo_url', ''))
        self.image_urls = safe_str(data.get('image_urls', ''))
        self.opening_hours = safe_str(data.get('opening_hours', ''))
        # rating/reviews restent bruts ici (float/int/None), convertis à l'usage
        self.rating = data.get('rating', None)
        self.reviews = data.get('reviews', None)
        self.google_maps = safe_str(data.get('google_maps', ''))
        self.source_url = safe_str(data.get('source_url', ''))
        self.scraped_at = safe_str(data.get('scraped_at', ''))

    def to_dict(self) -> Dict:
        return self.__dict__


class DataLoader:
    def __init__(self, filename: str, separator: str = ';', encoding: str = 'utf-8'):
        self.filename = filename
        self.separator = separator
        self.encoding = encoding
        self.entreprises: List[Entreprise] = []

    def load(self) -> List[Entreprise]:
        try:
            df = pd.read_csv(self.filename, sep=self.separator, encoding=self.encoding)
            df.columns = df.columns.str.strip()

            required = ['city', 'district', 'company_name', 'category', 'address']
            missing = [col for col in required if col not in df.columns]
            if missing:
                print(f"[⚠️] Colonnes manquantes : {missing}. La recherche sera moins précise.")

            for _, row in df.iterrows():
                data = row.to_dict()
                self.entreprises.append(Entreprise(data))

            print(f"[✅] {len(self.entreprises)} entreprises chargées depuis {self.filename}")
            return self.entreprises
        except FileNotFoundError:
            print(f"[❌] Fichier {self.filename} introuvable.")
            return []
        except Exception as e:
            print(f"[❌] Erreur lors du chargement : {e}")
            return []

    def _extract_keywords(self, query: str) -> List[str]:
        clean = re.sub(r'[^\w\s]', ' ', query.lower())
        words = clean.split()
        return [w for w in words if w not in STOP_WORDS and len(w) > 1]

    def search(self, query: str, limit: int = 5) -> List[Entreprise]:
        keywords = self._extract_keywords(query)
        if not keywords:
            keywords = [query.lower()]

        results = []
        for e in self.entreprises:
            # Tous les champs sont déjà des str propres grâce à safe_str() dans Entreprise
            text = ' '.join([
                e.company_name, e.category, e.city, e.district, e.address
            ]).lower()

            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                results.append((score, e))

        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results[:limit]]


# --- SerpApi ---
def search_online_with_images(query: str, limit: int = 5) -> List[Dict]:
    if not SERPAPI_KEY:
        print("[⚠️] SerpApi non configuré.")
        return []

    try:
        url = "https://serpapi.com/search"
        params = {
            'engine': 'google_maps',
            'type': 'search',
            'q': f"{query} Côte d'Ivoire",
            'api_key': SERPAPI_KEY,
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        results = []
        if 'local_results' in data:
            for item in data['local_results'][:limit]:
                name = item.get('title', 'Entreprise')
                address = item.get('address', '')
                phone = item.get('phone', '')
                place_id = item.get('place_id', '')
                photos = item.get('photos', [])
                image_url = photos[0] if photos else DEFAULT_IMAGE
                rating = safe_float(item.get('rating', 0.0))
                reviews = safe_int(item.get('reviews', 0))

                phone_link = f"tel:{phone}" if phone else ''
                whatsapp_link = (
                    f"https://api.whatsapp.com/send?phone={phone.replace(' ', '').replace('+', '')}"
                    if phone else ''
                )
                google_maps = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else ''

                results.append({
                    'company_name': name,
                    'category': 'Non spécifié',
                    'address': address,
                    'phone_link': phone_link,
                    'whatsapp_link': whatsapp_link,
                    'google_maps': google_maps,
                    'image': image_url,
                    'rating': rating,
                    'reviews': reviews,
                    'source': 'SerpApi Google Maps'
                })
            return results
        else:
            print(f"[⚠️] Aucun résultat local trouvé via SerpApi pour '{query}'")
            return []

    except Exception as e:
        print(f"[⚠️] Erreur SerpApi : {e}")
        return []


# --- Groq ---
def generate_response_with_groq(query: str, results: List[Dict]) -> str:
    if not GROQ_API_KEY:
        print("[⚠️] Groq non configuré.")
        return ""

    if not results:
        prompt = f"""
        L'utilisateur a cherché "{query}" mais je n'ai trouvé aucun résultat en ligne.
        Propose-lui des suggestions de recherche (autres mots-clés, catégories, lieux)
        en restant concis et utile.
        Réponds en français.
        """
    else:
        summary = "\n".join([
            f"- {r['company_name']} : {r.get('address', '')} (note {r.get('rating', 'N/A')}/5, {r.get('reviews', 0)} avis)"
            for r in results
        ])
        prompt = f"""
        L'utilisateur a cherché "{query}". Voici les entreprises trouvées :
        {summary}

        Rédige une réponse naturelle et engageante qui :
        - Mentionne le nombre de résultats.
        - Donne un aperçu des meilleures options.
        - Propose éventuellement un conseil (ex : appeler pour vérifier les horaires).
        - Reste court (max 100 mots).
        Réponds en français.
        """

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-70b-8192",
            "messages": [
                {"role": "system", "content": "Tu es un assistant utile qui répond aux questions sur les entreprises en Côte d'Ivoire."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 300
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data['choices'][0]['message']['content'].strip()
        else:
            print(f"[⚠️] Erreur Groq : {response.status_code} - {response.text}")
            return ""
    except Exception as e:
        print(f"[⚠️] Erreur lors de l'appel Groq : {e}")
        return ""


# --- Initialisation ---
loader = DataLoader(CSV_FILE, separator=SEPARATOR, encoding=ENCODING)
entreprises = loader.load()

if not entreprises:
    print("⚠️  Aucune entreprise chargée. Vérifiez le fichier CSV et son chemin.")

app = FastAPI(title="Annuaire CI API", version="5.9")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": getattr(exc, 'body', None)},
    )


@app.get("/models")
async def models():
    return {"message": "Route non utilisée. Utilisez /chat pour vos requêtes."}


@app.get("/v1/models")
async def v1_models():
    return {"message": "Route non utilisée. Utilisez /chat pour vos requêtes."}


class ChatRequest(BaseModel):
    message: str
    limit: int = 5


class CompanyResponse(BaseModel):
    company_name: str
    category: str
    address: str
    phone_link: str
    whatsapp_link: str
    google_maps: str
    image: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None


class ChatResponse(BaseModel):
    reply_text: str
    found: bool
    results: List[CompanyResponse]
    fallback_link: Optional[str] = None


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "entreprises_chargees": len(entreprises),
        "serpapi_configured": bool(SERPAPI_KEY),
        "groq_configured": bool(GROQ_API_KEY)
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_user_id: str = Header(...)
):
    if not x_user_id or x_user_id == "null" or x_user_id == "0":
        raise HTTPException(status_code=401, detail="Utilisateur non authentifié")

    query = request.message.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Message vide")

    # Recherche locale
    local_results = loader.search(query, limit=request.limit)
    if local_results:
        reply_text = f"J'ai trouvé {len(local_results)} résultat(s) dans ma base pour '{query}' :"
        companies = []
        for r in local_results:
            companies.append(CompanyResponse(
                company_name=r.company_name,
                category=r.category,
                address=r.address or r.city or r.district,
                phone_link=r.phone_link,
                whatsapp_link=r.whatsapp_link,
                google_maps=r.google_maps,
                image=r.logo_url or r.image_urls or DEFAULT_IMAGE,
                rating=safe_float(r.rating),
                reviews=safe_int(r.reviews)
            ))
        return ChatResponse(reply_text=reply_text, found=True, results=companies)

    # Recherche en ligne
    print(f"[🔍] Recherche en ligne via SerpApi pour : '{query}'")
    online_results = search_online_with_images(query, limit=request.limit)
    if online_results:
        groq_text = generate_response_with_groq(query, online_results)
        reply_text = groq_text if groq_text else f"J'ai trouvé {len(online_results)} résultat(s) pour '{query}' :"
        companies = [
            CompanyResponse(
                company_name=r['company_name'],
                category=r.get('category', 'Non spécifié'),
                address=r.get('address', ''),
                phone_link=r.get('phone_link', ''),
                whatsapp_link=r.get('whatsapp_link', ''),
                google_maps=r.get('google_maps', ''),
                image=r.get('image', DEFAULT_IMAGE),
                rating=r.get('rating'),
                reviews=r.get('reviews')
            )
            for r in online_results
        ]
        return ChatResponse(reply_text=reply_text, found=True, results=companies)

    # Aucun résultat
    groq_suggestion = generate_response_with_groq(query, [])
    reply_text = groq_suggestion if groq_suggestion else f"Je n'ai trouvé aucun résultat pour '{query}', ni localement ni en ligne."
    return ChatResponse(reply_text=reply_text, found=False, results=[])


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=PORT, reload=False)