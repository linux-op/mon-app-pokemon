import requests
import csv
from datetime import datetime
import os

# Liste des identifiants officiels des cartes que vous voulez suivre
# Ex: "base1-4" = Dracaufeu Set de Base, "sv3pt5-6" = Dracaufeu 151
cartes_a_suivre = ["base1-4", "sv3pt5-6", "xy1-1"]

fichier_csv = 'historique_prix.csv'
fichier_existe = os.path.isfile(fichier_csv)
date_actuelle = datetime.now().strftime("%Y-%m-%d")

nouvelles_donnees = []

print("Connexion à l'API pour récupérer les prix Cardmarket...")

for carte_id in cartes_a_suivre:
    url = f"https://api.pokemontcg.io/v2/cards/{carte_id}"
    # Le User-Agent évite d'être bloqué par l'API
    headers = {'User-Agent': 'Mozilla/5.0'}
    reponse = requests.get(url, headers=headers)
    
    if reponse.status_code == 200:
        data = reponse.json()['data']
        nom = data.get('name', 'Inconnu')
        
        try:
            # Extraction du prix moyen (trendPrice) de Cardmarket en Euros
            prix = data['cardmarket']['prices']['trendPrice']
        except KeyError:
            prix = "N/A"
            
        nouvelles_donnees.append([date_actuelle, carte_id, nom, prix])
        print(f"✅ {nom} ({carte_id}) : {prix} €")
    else:
        print(f"❌ Erreur pour la carte {carte_id}")

# Sauvegarde dans le fichier CSV
with open(fichier_csv, mode='a', newline='', encoding='utf-8') as fichier:
    writer = csv.writer(fichier)
    
    if not fichier_existe:
        # Création des colonnes la première fois
        writer.writerow(["Date", "ID_Carte", "Nom", "Prix_Cardmarket_EUR"])
        
    for ligne in nouvelles_donnees:
        writer.writerow(ligne)

print("Mise à jour terminée dans le fichier CSV.")