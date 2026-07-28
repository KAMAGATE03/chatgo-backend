#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Backend API pour Annuaire CI - Chat&Go
Version : 4.4 - Utilisation exclusive de SerpApi pour les recherches en ligne
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
ENCODING = "utf-8"

# Seule la clé SerpApi est conservée
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

PORT = int(os.environ.get("PORT", 8000))

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

class Entreprise:
    def __init__(self, data: Dict):
        self.company_id = data.get('company_id', '')
        self.company_name = data.get('company_name', '')
        self.category = data.get('category', '')
        self.description = data.get('description', '')
        self.lieu = data.get('lieu', '')
        self.address = data.get('address', '')
        self.latitude = data.get('latitude', '')
        self.longitude = data.get('longitude', '')
        self.phone = data.get('phone', '')
        self.phone_link = data.get('phone_link', '')
        self.whatsapp = data.get('whatsapp', '')
        self.whatsapp_link = data.get('whatsapp_link', '')
        self.email = data.get('email', '')
        self.email_link = data.get('email_link', '')
        self.website = data.get('website', '')
        self.facebook = data.get('facebook', '')
        self.instagram = data.get('instagram', '')
        self.logo_url = data.get('logo_url', '')
        self.image_urls = data.get('image_urls', '')
        self.opening_hours = data.get('opening_hours', '')
        self.rating = data.get('rating', '')
        self.reviews = data.get('reviews', '')
        self.google_maps = data.get('google_maps', '')
        self.source = data.get('source', '')
        self.scraped_at = data.get('scraped_at', '')

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
            for _, row in df.iterrows():
                data = row.to_dict()
                for k, v in data.items():
                    if isinstance(v, str):
                        data[k] = v.strip()
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
            score = 0
            text = (e.company_name + ' ' + e.category + ' ' + e.lieu + ' ' + e.address).lower()
            for kw in keywords:
                if kw in text:
                    score += 1
            if score > 0:
                results.append((score, e))

        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results[:limit]]

def search_online_with_images(query: str, limit: int = 5) -> List[Dict]:
    """
    Recherche en ligne UNIQUEMENT via SerpApi.
    Retourne une liste de dictionnaires avec les clés :
    - company_name, category, address, phone_link, whatsapp_link, google_maps, image_url, source
    """
    if not SERPAPI_KEY:
        print("[⚠️] SerpApi non configuré (SERPAPI_KEY manquante).")
        return []

    try:
        url = "https://serpapi.com/search"
        params = {
            'engine': 'google_images',
            'q': f"{query} entreprise Côte d'Ivoire",
            'api_key': SERPAPI_KEY,
            'num': limit,
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if 'images_results' in data:
            results = []
            for item in data['images_results']:
                title = item.get('title', '')
                name = title.split(' - ')[0] if ' - ' in title else title[:50]
                if not name:
                    name = 'Entreprise trouvée'
                results.append({
                    'company_name': name,
                    'category': 'Non spécifié',
                    'address': '',
                    'phone_link': '',
                    'whatsapp_link': '',
                    'google_maps': item.get('original', ''),
                    'image_url': item.get('original', ''),
                    'source': 'SerpApi (images)'
                })
            return results[:limit]
        else:
            print(f"[⚠️] Aucune image trouvée via SerpApi pour '{query}'")
            return []

    except Exception as e:
        print(f"[⚠️] Erreur SerpApi : {e}")
        return []

loader = DataLoader(CSV_FILE, separator=SEPARATOR, encoding=ENCODING)
entreprises = loader.load()

if not entreprises:
    print("⚠️  Aucune entreprise chargée.")

app = FastAPI(title="Chat&Go API", version="4.4")

# CORS
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
        content={"detail": exc.errors(), "body": exc.body},
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
    image_url: Optional[str] = None

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
        "serpapi_configured": bool(SERPAPI_KEY)
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

    # 1. RECHERCHE LOCALE
    local_results = loader.search(query, limit=request.limit)
    found_local = len(local_results) > 0

    if found_local:
        reply_text = f"J'ai trouvé {len(local_results)} entreprise(s) dans ma base :\n"
        for r in local_results:
            reply_text += f"- {r.company_name} ({r.category}) à {r.lieu}\n"
        reply_text += "Voici les fiches détaillées ci-dessous."

        companies = [
            CompanyResponse(
                company_name=r.company_name,
                category=r.category,
                address=r.address or r.lieu,
                phone_link=r.phone_link,
                whatsapp_link=r.whatsapp_link,
                google_maps=r.google_maps,
                image_url=r.logo_url or r.image_urls
            )
            for r in local_results
        ]
        return ChatResponse(
            reply_text=reply_text,
            found=True,
            results=companies,
            fallback_link=None
        )

    # 2. RECHERCHE EN LIGNE via SerpApi uniquement
    print(f"[🔍] Recherche en ligne via SerpApi pour : '{query}'")
    online_results = search_online_with_images(query, limit=request.limit)
    found_online = len(online_results) > 0

    if found_online:
        reply_text = f"Je n'ai pas trouvé dans ma base, mais voici des résultats en ligne pour '{query}' :\n"
        for r in online_results:
            reply_text += f"- {r['company_name']}\n"
        reply_text += "Ces informations proviennent de SerpApi."

        companies = [
            CompanyResponse(
                company_name=r['company_name'],
                category=r.get('category', 'Non spécifié'),
                address=r.get('address', ''),
                phone_link=r.get('phone_link', ''),
                whatsapp_link=r.get('whatsapp_link', ''),
                google_maps=r.get('google_maps', ''),
                image_url=r.get('image_url', '')
            )
            for r in online_results
        ]
        return ChatResponse(
            reply_text=reply_text,
            found=True,
            results=companies,
            fallback_link=None
        )

    # 3. AUCUN RÉSULTAT
    reply_text = f"Je n'ai trouvé aucun résultat pour '{query}', ni localement ni en ligne (via SerpApi)."
    return ChatResponse(
        reply_text=reply_text,
        found=False,
        results=[],
        fallback_link=None
    )

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=PORT, reload=False)