#!/usr/bin/env python3
"""
Script pour extraire et télécharger tous les souvenirs Snapchat depuis le fichier HTML
"""

import re
import os
import sys
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import time
import zipfile
import io
from PIL import Image
import argparse
import subprocess
import shutil
import tempfile


def check_ffmpeg_available():
    """
    Vérifie si ffmpeg est disponible sur le système
    
    Returns:
        True si ffmpeg est disponible, False sinon
    """
    return shutil.which('ffmpeg') is not None


def check_ffprobe_available():
    """
    Vérifie si ffprobe est disponible sur le système

    Returns:
        True si ffprobe est disponible, False sinon
    """
    return shutil.which('ffprobe') is not None


def get_video_dimensions(video_path):
    """
    Récupère les dimensions (largeur, hauteur) d'une vidéo via ffprobe

    Returns:
        Tuple (width, height) ou None si indisponible
    """
    if not check_ffprobe_available():
        return None
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0:s=x',
            video_path
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if not output or 'x' not in output:
            return None
        width_str, height_str = output.split('x', 1)
        width = int(width_str)
        height = int(height_str)
        return width, height
    except Exception:
        return None


def apply_overlay_to_video(video_path, overlay_path, output_path):
    """
    Applique un overlay sur une vidéo en utilisant ffmpeg
    
    Args:
        video_path: Chemin vers la vidéo de base
        overlay_path: Chemin vers l'image overlay (PNG avec transparence)
        output_path: Chemin de sortie pour la vidéo finale
        
    Returns:
        True si succès, False sinon
    """
    temp_overlay = None
    overlay_to_use = overlay_path
    try:
        if not check_ffmpeg_available():
            return False

        # Convertir l'overlay en PNG si nécessaire pour ffmpeg.
        try:
            img = Image.open(overlay_path)
            img.load()
            if img.format != 'PNG':
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                temp_overlay = temp_file.name
                temp_file.close()
                img = img.convert('RGBA')
                img.save(temp_overlay, 'PNG')
                overlay_to_use = temp_overlay
        except Exception:
            overlay_to_use = overlay_path

        # Construire le filtre en alignant l'overlay sur la taille de la video.
        video_dims = get_video_dimensions(video_path)
        if video_dims:
            even_width = video_dims[0] - (video_dims[0] % 2)
            even_height = video_dims[1] - (video_dims[1] % 2)
            filter_complex = (
                f"[0:v]scale={even_width}:{even_height},setsar=1[base];"
                f"[1:v]scale={even_width}:{even_height},format=rgba[ovr];"
                "[base][ovr]overlay=0:0:format=auto[v]"
            )
        else:
            filter_complex = (
                "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[base];"
                "[1:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=rgba[ovr];"
                "[base][ovr]overlay=0:0:format=auto[v]"
            )

        # Commande ffmpeg robuste: boucle l'image overlay et aligne les tailles.
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', video_path,
            '-loop', '1', '-i', overlay_to_use,
            '-filter_complex',
            filter_complex,
            '-map', '[v]',
            '-map', '0:a?',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'copy',
            '-shortest',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300
            )
        except subprocess.TimeoutExpired:
            print("   ⚠️  ffmpeg a dépassé le délai (300s)")
            return False

        if result.returncode != 0:
            if result.stderr:
                err = result.stderr.strip()
                if err:
                    print("   ⚠️  Erreur ffmpeg:")
                    print(err)
            return False

        # Vérifier que le fichier de sortie existe et n'est pas vide
        if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
            return True
        return False
    except Exception:
        return False
    finally:
        # Nettoyer le fichier temporaire
        if temp_overlay and os.path.exists(temp_overlay):
            try:
                os.remove(temp_overlay)
            except Exception:
                pass


def extract_download_links(html_file):
    """
    Extrait tous les liens de téléchargement du fichier HTML
    
    Args:
        html_file: Chemin vers le fichier HTML
        
    Returns:
        Liste de dictionnaires contenant les informations sur chaque fichier
    """
    print(f"📖 Lecture du fichier: {html_file}")
    
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern pour extraire les URLs dans les appels downloadMemories()
    pattern = r"downloadMemories\('(https://[^']+)'"
    
    matches = re.findall(pattern, content)
    
    print(f"✅ {len(matches)} liens de téléchargement trouvés\n")
    
    # Extraire aussi les métadonnées (date, type de média)
    soup = BeautifulSoup(content, 'html.parser')
    
    memories = []
    rows = soup.find_all('tr')
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= 4:
            # Extraire date, type de média et lien
            date_str = cells[0].get_text(strip=True)
            media_type = cells[1].get_text(strip=True)
            location = cells[2].get_text(strip=True)
            
            # Chercher le lien dans la dernière cellule
            link_cell = cells[3]
            onclick = link_cell.find('a', {'onclick': True})
            if onclick:
                onclick_text = onclick.get('onclick', '')
                url_match = re.search(r"downloadMemories\('(https://[^']+)'", onclick_text)
                if url_match:
                    url = url_match.group(1)
                    memories.append({
                        'date': date_str,
                        'type': media_type,
                        'location': location,
                        'url': url
                    })
    
    return memories


def apply_overlay_to_image(base_image_path, overlay_image_path, output_path):
    """
    Applique l'overlay (avec caption) sur l'image de base
    
    Args:
        base_image_path: Chemin vers l'image de base
        overlay_image_path: Chemin vers l'overlay
        output_path: Chemin de sortie pour l'image fusionnée
        
    Returns:
        True si succès, False sinon
    """
    try:
        print(f"\n      🔧 Ouverture de la base: {os.path.basename(base_image_path)}")
        print(f"      🔧 Ouverture de l'overlay: {os.path.basename(overlay_image_path)}")
        
        # Ouvrir les deux images
        base = Image.open(base_image_path)
        overlay = Image.open(overlay_image_path)
        
        print(f"      📐 Taille base: {base.size}, mode: {base.mode}")
        print(f"      📐 Taille overlay: {overlay.size}, mode: {overlay.mode}")
        
        # Convertir en RGBA pour la composition
        base = base.convert('RGBA')
        overlay = overlay.convert('RGBA')
        
        # S'assurer que l'overlay a la même taille que la base
        if overlay.size != base.size:
            print(f"      🔄 Redimensionnement overlay de {overlay.size} vers {base.size}")
            overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
        
        # Composite l'overlay sur la base
        print(f"      🎨 Composition des images...")
        combined = Image.alpha_composite(base, overlay)
        
        # Sauvegarder (convertir en RGB si nécessaire pour JPEG)
        if output_path.lower().endswith(('.jpg', '.jpeg')):
            print(f"      💾 Conversion en RGB pour JPEG")
            combined = combined.convert('RGB')
        
        print(f"      💾 Sauvegarde vers: {os.path.basename(output_path)}")
        combined.save(output_path, quality=95)
        print(f"      ✅ Succès!")
        return True
    except Exception as e:
        print(f"\n⚠️  Erreur lors de l'application de l'overlay: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def process_extracted_files(extract_folder, processed_folder, memory):
    """
    Traite les fichiers extraits: applique l'overlay et sauvegarde le résultat
    
    Args:
        extract_folder: Dossier contenant les fichiers extraits du ZIP
        processed_folder: Dossier de destination pour le fichier traité
        memory: Métadonnées du souvenir
        
    Returns:
        True si succès, False sinon
    """
    try:
        # Lister tous les fichiers dans le dossier extrait
        files = os.listdir(extract_folder)
        
        # Séparer les fichiers média et overlay
        media_file = None
        overlay_file = None
        
        # Chercher les fichiers avec -main et -overlay dans leur nom
        overlay_candidates = []
        overlay_exts = ('.png', '.webp', '.jpg', '.jpeg')
        for file in files:
            file_lower = file.lower()
            if '-overlay' in file_lower and file_lower.endswith(overlay_exts):
                overlay_candidates.append(file)
            elif '-main' in file_lower:
                media_file = os.path.join(extract_folder, file)

        if overlay_candidates:
            def overlay_priority(name):
                ext = os.path.splitext(name.lower())[1]
                if ext == '.png':
                    return 0
                if ext == '.webp':
                    return 1
                if ext in ('.jpg', '.jpeg'):
                    return 2
                return 99
            overlay_candidates.sort(key=overlay_priority)
            overlay_file = os.path.join(extract_folder, overlay_candidates[0])
        
        print(f"\n   📁 Fichiers trouvés: {files}")
        print(f"   🎬 Média: {os.path.basename(media_file) if media_file else 'Non trouvé'}")
        print(f"   🎨 Overlay: {os.path.basename(overlay_file) if overlay_file else 'Non trouvé'}")
        
        if not media_file:
            # Pas de fichier média trouvé
            print(f"   ⚠️  Aucun fichier média trouvé!")
            return False
        
        # Déterminer le nom de fichier de sortie à partir du nom du média
        media_basename = os.path.basename(media_file)
        media_stem, media_ext = os.path.splitext(media_basename)
        if media_stem.endswith('-main'):
            base_id = media_stem[:-5]
        else:
            base_id = media_stem
        output_file = os.path.join(processed_folder, f"{base_id}-processed{media_ext}")
        
        # Pour les vidéos, on ne peut pas appliquer l'overlay facilement
        if media_file.lower().endswith(('.mp4', '.mov')):
            
            # Essayer d'appliquer l'overlay avec ffmpeg
            if overlay_file and check_ffmpeg_available():
                print(f"   ✨ Application de l'overlay avec ffmpeg...")
                success = apply_overlay_to_video(media_file, overlay_file, output_file)
                
                if success:
                    print(f"   ✅ Overlay appliqué avec succès!")
                else:
                    print(f"   ⚠️  Échec ffmpeg, copie sans overlay")
                    # Copier sans overlay
                    with open(media_file, 'rb') as src:
                        with open(output_file, 'wb') as dst:
                            dst.write(src.read())
            else:
                # Pas de ffmpeg ou pas d'overlay
                if not check_ffmpeg_available() and overlay_file:
                    print(f"   ⚠️  ffmpeg non disponible, copie sans overlay")
                
                with open(media_file, 'rb') as src:
                    with open(output_file, 'wb') as dst:
                        dst.write(src.read())
        
        # Pour les images, appliquer l'overlay
        elif media_file.lower().endswith(('.jpg', '.jpeg', '.png')):
            
            if overlay_file:
                # Appliquer l'overlay sur l'image
                print(f"   ✨ Application de l'overlay...", end=' ')
                success = apply_overlay_to_image(media_file, overlay_file, output_file)
                if success:
                    print("✅")
                else:
                    print("❌")
                    # Si échec, copier l'image originale
                    with open(media_file, 'rb') as src:
                        with open(output_file, 'wb') as dst:
                            dst.write(src.read())
            else:
                # Pas d'overlay, copier l'image telle quelle
                with open(media_file, 'rb') as src:
                    with open(output_file, 'wb') as dst:
                        dst.write(src.read())
        
        # Définir le timestamp uniquement pour le fichier de sortie
        if os.path.exists(output_file):
            apply_timestamp(output_file, memory)
        
        return True
    except Exception as e:
        print(f"\n⚠️  Erreur lors du traitement: {str(e)}")
        return False


def generate_filename(memory, index):
    """
    Génère un nom de fichier unique basé sur les métadonnées
    
    Args:
        memory: Dictionnaire avec les infos du souvenir
        index: Index du fichier
        
    Returns:
        Nom de fichier généré
    """
    # Extraire la date et nettoyer
    date_str = memory['date']
    try:
        # Format: "2025-12-22 23:03:10 UTC"
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S UTC")
        date_formatted = date_obj.strftime("%Y%m%d_%H%M%S")
    except:
        date_formatted = f"memory_{index:04d}"
    
    # Déterminer l'extension selon le type
    media_type = memory['type'].lower()
    if 'video' in media_type:
        extension = 'mp4'
    elif 'image' in media_type:
        extension = 'jpg'
    else:
        extension = 'dat'
    
    filename = f"{date_formatted}_{media_type}.{extension}"
    
    return filename


def apply_timestamp(file_path, memory):
    """
    Applique le timestamp du souvenir au fichier donné
    """
    if not memory or not memory.get('date'):
        return
    try:
        date_obj = datetime.strptime(memory['date'], "%Y-%m-%d %H:%M:%S UTC")
        timestamp = date_obj.timestamp()
        os.utime(file_path, (timestamp, timestamp))
    except Exception:
        pass


def select_test_memories(memories, video_limit=2, image_limit=2):
    """
    Sélectionne un sous-ensemble de souvenirs pour le mode test

    Args:
        memories: Liste des souvenirs
        video_limit: Nombre max de vidéos
        image_limit: Nombre max d'images

    Returns:
        Liste filtrée des souvenirs
    """
    selected = []
    video_count = 0
    image_count = 0

    for memory in memories:
        media_type = memory.get('type', '').lower()
        if 'video' in media_type and video_count < video_limit:
            selected.append(memory)
            video_count += 1
        elif 'image' in media_type and image_count < image_limit:
            selected.append(memory)
            image_count += 1

        if video_count >= video_limit and image_count >= image_limit:
            break

    return selected


def download_file(url, destination, processed_destination, filename, index, total, memory=None):
    """
    Télécharge un fichier depuis une URL, extrait le ZIP et applique l'overlay
    
    Args:
        url: URL du fichier
        destination: Répertoire de destination pour les extraits temporaires
        processed_destination: Répertoire pour les fichiers traités
        filename: Nom du fichier (utilisé comme nom de dossier)
        index: Numéro du fichier en cours
        total: Nombre total de fichiers
        memory: Dictionnaire avec les métadonnées du souvenir (optionnel)
        
    Returns:
        True si succès, False sinon
    """
    # Créer un dossier temporaire pour ce souvenir (sans l'extension)
    folder_name = os.path.splitext(filename)[0]
    folder_path = os.path.join(destination, folder_name)
    
    # Vérifier si déjà traité
    date_str = memory.get('date', '') if memory else ''
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S UTC")
        date_formatted = date_obj.strftime("%Y%m%d_%H%M%S")
    except:
        date_formatted = f"memory_{index:04d}"
    
    # Vérifier si des fichiers avec ce timestamp existent déjà
    if os.path.exists(processed_destination):
        existing_files = [f for f in os.listdir(processed_destination) if f.startswith(date_formatted)]
        if existing_files:
            print(f"⏭️  [{index}/{total}] Déjà traité: {date_formatted}")
            return True
    
    try:
        print(f"⬇️  [{index}/{total}] Téléchargement: {folder_name}...", end=' ', flush=True)
        
        # Télécharger avec un timeout
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Lire le contenu
        content = b''
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                content += chunk
        
        file_size = len(content) / (1024 * 1024)  # En MB
        
        # Vérifier si c'est un fichier ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                # C'est un ZIP, l'extraire dans un dossier temporaire
                os.makedirs(folder_path, exist_ok=True)
                zip_file.extractall(folder_path)
                
                print(f"✅ ({file_size:.2f} MB)", end=' ')
                
                # Créer le dossier de destination s'il n'existe pas
                os.makedirs(processed_destination, exist_ok=True)
                
                # Traiter les fichiers extraits (appliquer overlay)
                success = process_extracted_files(folder_path, processed_destination, memory)
                
                if success:
                    print("→ 🎨 Traité")
                else:
                    print("→ ⚠️  Copié sans overlay")
                
                # Garder le dossier temporaire avec les fichiers bruts
                
        except zipfile.BadZipFile:
            # Ce n'est pas un ZIP, sauvegarder comme fichier unique dans processed
            os.makedirs(processed_destination, exist_ok=True)
            filepath = os.path.join(processed_destination, filename)
            
            with open(filepath, 'wb') as f:
                f.write(content)
            
            # Définir le timestamp
            apply_timestamp(filepath, memory)
            
            print(f"✅ ({file_size:.2f} MB)")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue: {str(e)}")
        return False


def main():
    """Fonction principale"""
    
    # Parser les arguments
    parser = argparse.ArgumentParser(
        description='Téléchargeur de souvenirs Snapchat',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Exemples:
  %(prog)s                                    # Utilise les valeurs par défaut
  %(prog)s --html mon_fichier.html            # Spécifie le fichier HTML
  %(prog)s --test                             # Mode test (5 fichiers)
  %(prog)s --html fichier.html --test         # Combine les options
        ''')
    
    parser.add_argument(
        '--html',
        default='./html/memories_history.html',
        help='Chemin vers le fichier HTML Snapchat (défaut: ./html/memories_history.html)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Mode test: limite à 5 fichiers'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limite le nombre de fichiers à télécharger (remplace --test)'
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("📸 TÉLÉCHARGEUR DE SOUVENIRS SNAPCHAT")
    print("=" * 70)
    print()

    # Vérifier la disponibilité de ffmpeg/ffprobe avant toute exécution
    if not check_ffmpeg_available() or not check_ffprobe_available():
        print("❌ Erreur: ffmpeg et ffprobe sont requis pour exécuter ce script.")
        print("   Installez ffmpeg puis relancez.")
        sys.exit(1)
    
    # Vérifier l'existence du fichier HTML
    html_file = args.html
    if not os.path.exists(html_file):
        print(f"❌ Erreur: Le fichier '{html_file}' n'existe pas!")
        sys.exit(1)
    
    # Extraire les liens
    memories = extract_download_links(html_file)
    
    if not memories:
        print("❌ Aucun lien de téléchargement trouvé dans le fichier HTML!")
        sys.exit(1)
    
    # Afficher un résumé
    video_count = sum(1 for m in memories if 'video' in m['type'].lower())
    image_count = sum(1 for m in memories if 'image' in m['type'].lower())
    
    print(f"📊 Résumé:")
    print(f"   • Vidéos: {video_count}")
    print(f"   • Images: {image_count}")
    print(f"   • Total: {len(memories)}")
    print()
    
    # Appliquer la limite si spécifiée
    if args.limit:
        memories = memories[:args.limit]
        print(f"✅ Limite appliquée: {len(memories)} fichiers")
        print()
    elif args.test:
        memories = select_test_memories(memories, video_limit=2, image_limit=2)
        selected_videos = sum(1 for m in memories if 'video' in m.get('type', '').lower())
        selected_images = sum(1 for m in memories if 'image' in m.get('type', '').lower())
        print(f"✅ Mode test activé: {len(memories)} fichiers")
        print(f"   • Vidéos: {selected_videos}")
        print(f"   • Images: {selected_images}")
        print()
    
    # Répertoires de destination
    temp_dest = "snapchat_memories_raw"
    processed_dest = "snapchat_memories_processed"
    
    # Créer les répertoires s'ils n'existent pas
    Path(temp_dest).mkdir(parents=True, exist_ok=True)
    Path(processed_dest).mkdir(parents=True, exist_ok=True)
    print(f"✅ Répertoires créés/vérifiés:")
    print(f"   • Raw: {temp_dest}")
    print(f"   • Traité: {processed_dest}")
    print()
    
    print()
    print("=" * 70)
    print("⬇️  DÉBUT DU TÉLÉCHARGEMENT")
    print("=" * 70)
    print()
    
    # Télécharger tous les fichiers
    success_count = 0
    failed_count = 0
    start_time = time.time()
    
    for index, memory in enumerate(memories, 1):
        filename = generate_filename(memory, index)
        
        if download_file(memory['url'], temp_dest, processed_dest, filename, index, len(memories), memory):
            success_count += 1
        else:
            failed_count += 1
        
        # Petite pause entre les téléchargements pour ne pas surcharger le serveur
        if index < len(memories):
            time.sleep(0.5)
    
    # Résumé final
    elapsed_time = time.time() - start_time
    
    print()
    print("=" * 70)
    print("✅ TÉLÉCHARGEMENT TERMINÉ")
    print("=" * 70)
    print(f"✅ Réussis: {success_count}/{len(memories)}")
    if failed_count > 0:
        print(f"❌ Échoués: {failed_count}/{len(memories)}")
    print(f"⏱️  Temps écoulé: {elapsed_time:.1f} secondes")
    print(f"📁 Fichiers traités dans: {os.path.abspath(processed_dest)}")
    print(f"📁 Fichiers bruts dans: {os.path.abspath(temp_dest)}")
    print()
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Téléchargement interrompu par l'utilisateur.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Erreur fatale: {str(e)}")
        sys.exit(1)
