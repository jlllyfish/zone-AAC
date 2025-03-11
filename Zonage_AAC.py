import streamlit as st
import pandas as pd
import json
from shapely.geometry import Point, shape
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import time
import re

# Configuration de la page (plus simple)
st.set_page_config(page_title="Vérificateur de Zones AAC", page_icon="🌊", layout="wide")

# Titre
st.title("Vérificateur de Zones AAC (Aire d'Alimentation de Captage)")

# Fonction de géocodage simplifiée
def get_coordinates(address):
    with st.spinner("Recherche des coordonnées..."):
        try:
            geolocator = Nominatim(user_agent="aac_checker")
            time.sleep(1)  # Respect des limites de l'API
            location = geolocator.geocode(address)
            if location:
                return (location.latitude, location.longitude)
        except Exception as e:
            st.error(f"Erreur de géocodage: {str(e)}")
    return None

# Fonction pour vérifier si un point est dans une zone AAC
def is_in_aac(lat, lon, aac_features):
    try:
        point = Point(lon, lat)
        point_buffer = point.buffer(0.0001)  # Environ 10-15m
        
        for feature in aac_features:
            try:
                aac_shape = shape(feature['geometry'])
                properties = feature['properties']
                
                # Vérification directe
                if aac_shape.contains(point) or aac_shape.intersects(point_buffer):
                    return True, properties
            except:
                continue
        
        return False, None
    except:
        return False, None

# Structure à deux colonnes
col1, col2 = st.columns([1, 3])

# Colonne de gauche pour le chargement du fichier
with col1:
    st.header("Chargement des données")
    uploaded_file = st.file_uploader("Fichier GeoJSON des AAC", type=["geojson", "json"])
    
    # Variables pour stocker les données
    geojson_data = None
    
    if uploaded_file:
        try:
            geojson_data = json.load(uploaded_file)
            st.success(f"{len(geojson_data['features'])} zones détectées")
        except:
            st.error("Erreur: Format de fichier invalide")

# Colonne de droite pour la vérification
with col2:
    st.header("Vérification")
    
    # Initialisation des variables de session si elles n'existent pas
    if 'reset_pressed' not in st.session_state:
        st.session_state.reset_pressed = False
    if 'last_address' not in st.session_state:
        st.session_state.last_address = ""
    if 'last_lat' not in st.session_state:
        st.session_state.last_lat = 46.603354
    if 'last_lon' not in st.session_state:
        st.session_state.last_lon = 1.888334
    
    # Fonction pour réinitialiser les champs
    def reset_fields():
        st.session_state.reset_pressed = True
        st.session_state.last_address = ""
        st.session_state.last_lat = 46.603354
        st.session_state.last_lon = 1.888334
    
    # Bouton de réinitialisation
    reset_col, spacer = st.columns([1, 3])
    with reset_col:
        st.button("🔄 Nouvelle recherche", on_click=reset_fields, help="Réinitialiser les champs et effacer les résultats")
    
    # Mode de saisie
    input_mode = st.radio("Mode", ["Adresse", "Coordonnées"])
    
    # Placeholder pour les résultats (vide au début)
    results_placeholder = st.empty()
    
    # Conteneur pour les résultats
    with results_placeholder.container():
        if input_mode == "Adresse":
            # Utiliser la dernière adresse ou une chaîne vide si réinitialisation
            if st.session_state.reset_pressed:
                initial_address = ""
                st.session_state.reset_pressed = False  # Réinitialiser le flag
            else:
                initial_address = st.session_state.last_address
                
            address = st.text_input("Entrez une adresse", value=initial_address)
            # Stocker l'adresse actuelle
            st.session_state.last_address = address
            
            check_button = st.button("Vérifier l'adresse")
            
            # Ne continuer que si on a cliqué sur le bouton et qu'un fichier est chargé
            if check_button and address:
                if not geojson_data:
                    st.error("Veuillez d'abord charger un fichier GeoJSON")
                else:
                    # Effacer le contenu du placeholder
                    results_placeholder.empty()
                    
                    # Recréer un conteneur pour les nouveaux résultats
                    with results_placeholder.container():
                        st.write(f"Adresse saisie: {address}")
                        
                        # Géocodage
                        coordinates = get_coordinates(address)
                        if coordinates:
                            lat, lon = coordinates
                            st.write(f"Coordonnées: {lat}, {lon}")
                            
                            # Vérification AAC
                            in_aac, properties = is_in_aac(lat, lon, geojson_data['features'])
                            
                            # Afficher le résultat textuel
                            if in_aac:
                                st.success("✅ Cette adresse est située dans une AAC")
                                
                                # Infos sur la zone
                                st.subheader("Informations sur la zone:")
                                df = pd.DataFrame(list(properties.items()), 
                                                columns=["Propriété", "Valeur"])
                                st.dataframe(df)
                            else:
                                st.warning("❌ Cette adresse n'est pas dans une AAC")
                            
                            # Maintenant on crée et affiche la carte
                            st.subheader("Carte")
                            
                            # Carte de base
                            m = folium.Map(location=[lat, lon], zoom_start=12)
                            
                            # Ajouter les zones AAC
                            for feature in geojson_data['features']:
                                try:
                                    # Style de base
                                    style = {
                                        'fillColor': '#81C6E8',
                                        'color': '#1F75C4',
                                        'fillOpacity': 0.4,
                                        'weight': 1.5
                                    }
                                    
                                    # Mettre en évidence la zone si on est dedans
                                    if in_aac and properties == feature['properties']:
                                        style = {
                                            'fillColor': '#4CAF50',
                                            'color': '#2E7D32',
                                            'fillOpacity': 0.6,
                                            'weight': 2.5
                                        }
                                    
                                    # Ajouter le polygone
                                    folium.GeoJson(
                                        feature,
                                        style_function=lambda x, style=style: style
                                    ).add_to(m)
                                except:
                                    continue
                            
                            # Ajouter le marqueur APRÈS les polygones
                            marker_color = "green" if in_aac else "red"
                            folium.Marker(
                                [lat, lon],
                                popup=f"<b>{address}</b>",
                                icon=folium.Icon(color=marker_color, icon="info-sign")
                            ).add_to(m)
                            
                            # Afficher la carte
                            st_folium(m, width=900, height=500, returned_objects=[])
                            
                            # Ajouter un bouton pour refaire une recherche
                            if st.button("🔄 Faire une nouvelle recherche", key="new_search_addr"):
                                st.session_state.reset_pressed = True
                                st.session_state.last_address = ""
                                st.rerun()  # Forcer le rechargement de la page
                        else:
                            st.error("Impossible de géocoder cette adresse")
                            
        else:  # Mode Coordonnées
            # Utiliser les dernières coordonnées ou les valeurs par défaut si réinitialisation
            if st.session_state.reset_pressed:
                initial_lat = 46.603354
                initial_lon = 1.888334
                st.session_state.reset_pressed = False  # Réinitialiser le flag
            else:
                initial_lat = st.session_state.last_lat
                initial_lon = st.session_state.last_lon
            
            lat_col, lon_col = st.columns(2)
            with lat_col:
                lat = st.number_input("Latitude", value=initial_lat, format="%.6f")
            with lon_col:
                lon = st.number_input("Longitude", value=initial_lon, format="%.6f")
            
            # Stocker les coordonnées actuelles
            st.session_state.last_lat = lat
            st.session_state.last_lon = lon
            
            check_button = st.button("Vérifier les coordonnées")
            
            if check_button:
                if not geojson_data:
                    st.error("Veuillez d'abord charger un fichier GeoJSON")
                else:
                    # Effacer le contenu du placeholder
                    results_placeholder.empty()
                    
                    # Recréer un conteneur pour les nouveaux résultats
                    with results_placeholder.container():
                        st.write(f"Coordonnées: {lat}, {lon}")
                        
                        # Vérification AAC
                        in_aac, properties = is_in_aac(lat, lon, geojson_data['features'])
                        
                        # Afficher le résultat
                        if in_aac:
                            st.success("✅ Ces coordonnées sont dans une AAC")
                            
                            # Infos sur la zone
                            st.subheader("Informations sur la zone:")
                            df = pd.DataFrame(list(properties.items()), 
                                             columns=["Propriété", "Valeur"])
                            st.dataframe(df)
                        else:
                            st.warning("❌ Ces coordonnées ne sont pas dans une AAC")
                        
                        # Créer et afficher la carte
                        st.subheader("Carte")
                        
                        # Carte de base
                        m = folium.Map(location=[lat, lon], zoom_start=12)
                        
                        # Ajouter les zones AAC
                        for feature in geojson_data['features']:
                            try:
                                # Style de base
                                style = {
                                    'fillColor': '#81C6E8',
                                    'color': '#1F75C4',
                                    'fillOpacity': 0.4,
                                    'weight': 1.5
                                }
                                
                                # Mettre en évidence la zone si on est dedans
                                if in_aac and properties == feature['properties']:
                                    style = {
                                        'fillColor': '#4CAF50',
                                        'color': '#2E7D32',
                                        'fillOpacity': 0.6,
                                        'weight': 2.5
                                    }
                                
                                # Ajouter le polygone
                                folium.GeoJson(
                                    feature,
                                    style_function=lambda x, style=style: style
                                ).add_to(m)
                            except:
                                continue
                        
                        # Ajouter le marqueur APRÈS les polygones
                        marker_color = "green" if in_aac else "red"
                        folium.Marker(
                            [lat, lon],
                            popup=f"<b>Coordonnées: {lat}, {lon}</b>",
                            icon=folium.Icon(color=marker_color, icon="info-sign")
                        ).add_to(m)
                        
                        # Afficher la carte
                        st_folium(m, width=900, height=500, returned_objects=[])
                        
                        # Ajouter un bouton pour refaire une recherche
                        if st.button("🔄 Faire une nouvelle recherche", key="new_search_coords"):
                            st.session_state.reset_pressed = True
                            st.session_state.last_lat = 46.603354
                            st.session_state.last_lon = 1.888334
                            st.rerun()  # Forcer le rechargement de la page

# Pied de page
st.markdown("---")
st.info("""Cette application vérifie si une adresse ou des coordonnées GPS sont situées dans une 
        Aire d'Alimentation de Captage (AAC).""")