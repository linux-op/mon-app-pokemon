import csv
from datetime import datetime

donnees = [{"id": "base1-4", "nom": "Dracaufeu", "prix": 120.50}]
date_jour = datetime.now().strftime("%Y-%m-%d")

# Ouvre le fichier en mode "ajout" (append) pour ne pas écraser l'historique
with open('historique_prix.csv', 'a', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    for c in donnees:
        writer.writerow([date_jour, c['id'], c['nom'], c['prix']])
