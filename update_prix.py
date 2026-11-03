#!/usr/bin/env python3
"""Exporte les prix de toutes les cartes Pokémon (noms FR + EN) via l'API gratuite TCGdex.

Sources de prix fournies par TCGdex : Cardmarket (EUR) et TCGplayer (USD).
Aucune clé d'API, aucune dépendance externe (bibliothèque standard uniquement).

Sorties (dans --out) :
  prices.sqlite   historique (une ligne seulement quand un prix change)
  latest.csv      snapshot complet du jour (une ligne par carte)
"""
import argparse
import csv
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

UA = "pokemon-price-exporter/1.0 (github actions, personal project)"


def get_json(url, retries=5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # réseau, JSON tronqué...
            err = e
        time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"échec {url}: {err}")


def flatten(obj, prefix=""):
    """{'cardmarket': {'avg': 1, 'holo': {'avg': 2}}} -> ('cardmarket','avg',1), ('cardmarket','holo.avg',2)"""
    for k, v in obj.items():
        if isinstance(v, dict):
            yield from flatten(v, f"{prefix}{k}.")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            yield prefix + k, v


def card_prices(pricing):
    out = {}
    for source, data in (pricing or {}).items():
        if isinstance(data, dict):
            for metric, value in flatten(data):
                out[(source, metric)] = value
    return out


def init_db(path):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cards(
            card_id TEXT PRIMARY KEY, local_id TEXT, set_id TEXT,
            set_en TEXT, set_fr TEXT, name_en TEXT, name_fr TEXT, rarity TEXT);
        CREATE TABLE IF NOT EXISTS latest(
            card_id TEXT, source TEXT, metric TEXT, value REAL, date TEXT,
            PRIMARY KEY(card_id, source, metric));
        CREATE TABLE IF NOT EXISTS history(
            date TEXT, card_id TEXT, source TEXT, metric TEXT, value REAL);
        CREATE INDEX IF NOT EXISTS history_card ON history(card_id, date);
        """
    )
    return db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--base", default="https://api.tcgdex.net/v2")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="debug: nb de cartes max")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    print("Liste des cartes EN / FR...")
    en = {c["id"]: c for c in get_json(f"{args.base}/en/cards") or []}
    fr = {c["id"]: c for c in get_json(f"{args.base}/fr/cards") or []}
    ids = sorted(set(en) | set(fr))
    if args.limit:
        ids = ids[: args.limit]
    print(f"{len(ids)} cartes ({len(en)} EN, {len(fr)} FR)")

    # Les prix sont rattachés à la carte (même id en FR et EN) : on ne les
    # télécharge qu'une fois (EN, ou FR si la carte n'existe qu'en français).
    # Le nom de la langue manquante vient de la liste ci-dessus.
    def fetch(cid):
        lang = "en" if cid in en else "fr"
        card = get_json(f"{args.base}/{lang}/cards/{cid}")
        return cid, lang, card

    results, failed = {}, []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(fetch, cid) for cid in ids]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                cid, lang, card = f.result()
                if card:
                    results[cid] = (lang, card)
            except Exception as e:
                failed.append(str(e))
            if i % 1000 == 0:
                print(f"  {i}/{len(ids)}")

    if len(failed) > 0.05 * len(ids):
        print(f"Trop d'échecs ({len(failed)}), abandon sans modifier la base.", file=sys.stderr)
        print("\n".join(failed[:5]), file=sys.stderr)
        sys.exit(1)

    db = init_db(out / "prices.sqlite")
    changes = 0
    rows = []
    metrics_seen = set()
    for cid, (lang, card) in results.items():
        s = card.get("set") or {}
        name_en = (en.get(cid) or {}).get("name") or (card["name"] if lang == "en" else "")
        name_fr = (fr.get(cid) or {}).get("name") or (card["name"] if lang == "fr" else "")
        row = {
            "card_id": cid,
            "local_id": card.get("localId", ""),
            "set_id": s.get("id", ""),
            "set_en": s.get("name", "") if lang == "en" else "",
            "set_fr": s.get("name", "") if lang == "fr" else "",
            "name_en": name_en,
            "name_fr": name_fr,
            "rarity": card.get("rarity", ""),
        }
        db.execute(
            """INSERT INTO cards VALUES(:card_id,:local_id,:set_id,:set_en,:set_fr,:name_en,:name_fr,:rarity)
               ON CONFLICT(card_id) DO UPDATE SET
                 local_id=excluded.local_id, set_id=excluded.set_id,
                 set_en=COALESCE(NULLIF(excluded.set_en,''), set_en),
                 set_fr=COALESCE(NULLIF(excluded.set_fr,''), set_fr),
                 name_en=COALESCE(NULLIF(excluded.name_en,''), name_en),
                 name_fr=COALESCE(NULLIF(excluded.name_fr,''), name_fr),
                 rarity=excluded.rarity""",
            row,
        )
        prices = card_prices(card.get("pricing"))
        for (source, metric), value in prices.items():
            key = f"{source}.{metric}"
            metrics_seen.add(key)
            row[key] = value
            old = db.execute(
                "SELECT value FROM latest WHERE card_id=? AND source=? AND metric=?",
                (cid, source, metric),
            ).fetchone()
            if old is None or old[0] != value:
                db.execute("INSERT INTO history VALUES(?,?,?,?,?)", (today, cid, source, metric, value))
                changes += 1
            db.execute(
                "INSERT OR REPLACE INTO latest VALUES(?,?,?,?,?)", (cid, source, metric, value, today)
            )
        rows.append(row)
    db.commit()
    db.close()

    base_cols = ["card_id", "local_id", "set_id", "set_en", "set_fr", "name_en", "name_fr", "rarity"]
    cols = base_cols + sorted(metrics_seen)
    with open(out / "latest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["card_id"]))

    print(f"OK : {len(rows)} cartes, {changes} prix modifiés, {len(failed)} échecs ignorés.")


if __name__ == "__main__":
    main()
