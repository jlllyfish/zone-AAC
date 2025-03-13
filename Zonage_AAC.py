import streamlit as st
import pandas as pd
import json
from shapely.geometry import Point, shape
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import time
import re
import geopandas as gpd

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
def is_in_aac(lat, lon, data_source):
    try:
        point = Point(lon, lat)
        
        # Si c'est un GeoDataFrame (GPKG), on utilise les fonctionnalités spatiales de GeoPandas
        if isinstance(data_source, gpd.GeoDataFrame):
            # S'assurer que le GeoDataFrame a un CRS défini
            if data_source.crs is None:
                st.warning("Le fichier GPKG n'a pas de système de coordonnées défini. On suppose WGS84 (EPSG:4326).")
                data_source.set_crs(epsg=4326, inplace=True)
            
            # Créer un GeoDataFrame avec le point en WGS84 (coordonnées GPS standard)
            point_gdf = gpd.GeoDataFrame(geometry=[point], crs="EPSG:4326")
            
            # Convertir le point dans le même CRS que le GeoDataFrame si nécessaire
            if point_gdf.crs != data_source.crs:
                point_gdf = point_gdf.to_crs(data_source.crs)
            
            # Méthode 1: Spatial join pour trouver les polygones qui contiennent le point
            try:
                intersects = gpd.sjoin(point_gdf, data_source, how="left", predicate="within")
                if not intersects.empty and 'index_right' in intersects.columns and not intersects['index_right'].isna().all():
                    # Récupérer les propriétés du premier polygone qui contient le point
                    match_idx = intersects['index_right'].dropna().iloc[0]
                    properties = data_source.loc[match_idx].drop('geometry').to_dict()
                    return True, properties
            except Exception as e:
                st.warning(f"Méthode de jointure spatiale non concluante: {str(e)}. Essai avec d'autres méthodes...")
            
            # Méthode 2: Vérification directe avec un buffer
            try:
                # Créer un buffer autour du point (100 mètres)
                buffer_size = 0.001  # environ 100m en degrés
                buffer = point_gdf.geometry[0].buffer(buffer_size)
                buffer_gdf = gpd.GeoDataFrame(geometry=[buffer], crs=point_gdf.crs)
                
                # Vérifier les intersections avec le buffer
                for idx, row in data_source.iterrows():
                    if row.geometry.intersects(buffer):
                        properties = row.drop('geometry').to_dict()
                        return True, properties
            except Exception as e:
                st.warning(f"Méthode de buffer non concluante: {str(e)}. Essai avec la méthode manuelle...")
            
            # Méthode 3: Vérification manuelle - dernier recours
            try:
                for idx, row in data_source.iterrows():
                    if row.geometry.contains(point_gdf.geometry[0]):
                        properties = row.drop('geometry').to_dict()
                        return True, properties
            except Exception as e:
                st.warning(f"Méthode manuelle échouée: {str(e)}")
                
            # Afficher des informations de débogage
            st.info(f"Point de test: {lat}, {lon} - CRS du point: {point_gdf.crs} - CRS des données: {data_source.crs}")
            
        # Si c'est un GeoJSON
        else:
            point_buffer = point.buffer(0.0001)  # Environ 10-15m
            for feature in data_source['features']:
                try:
                    aac_shape = shape(feature['geometry'])
                    properties = feature['properties']
                    
                    # Vérification directe
                    if aac_shape.contains(point) or aac_shape.intersects(point_buffer):
                        return True, properties
                except Exception as e:
                    st.warning(f"Erreur lors de la vérification d'une feature GeoJSON: {str(e)}")
                    continue
        
        return False, None
    except Exception as e:
        st.error(f"Erreur lors de la vérification des zones: {str(e)}")
        return False, None

# Structure à deux colonnes
col1, col2 = st.columns([1, 3])

# Colonne de gauche pour le chargement du fichier
with col1:
    st.header("Chargement des données")
    uploaded_file = st.file_uploader("Fichier des AAC", type=["geojson", "json", "gpkg"])
    
    # Variables pour stocker les données
    data_source = None
    file_type = None
    
    # Options de filtrage régional
    st.subheader("Options de filtrage")
    filter_by_region = st.checkbox("Filtrer par région", value=True)
    
    if filter_by_region:
        regions = ["Occitanie", "Nouvelle-Aquitaine", "Auvergne-Rhône-Alpes", "Provence-Alpes-Côte d'Azur", 
                  "Île-de-France", "Hauts-de-France", "Grand Est", "Bourgogne-Franche-Comté", 
                  "Centre-Val de Loire", "Pays de la Loire", "Bretagne", "Normandie", "Corse", "France entière"]
        selected_region = st.selectbox("Sélectionner une région", regions, index=0)
    
    if uploaded_file:
        try:
            file_extension = uploaded_file.name.split('.')[-1].lower()
            
            if file_extension in ['geojson', 'json']:
                data_source = json.load(uploaded_file)
                
                if filter_by_region:
                    st.warning("Le filtrage par région est uniquement disponible pour les fichiers GPKG. Les fichiers GeoJSON sont chargés en entier.")
                
                st.success(f"{len(data_source['features'])} zones détectées")
                file_type = "geojson"
                
            elif file_extension == 'gpkg':
                # Utiliser geopandas pour lire le GeoPackage
                with st.spinner("Chargement du fichier GPKG..."):
                    gdf = gpd.read_file(uploaded_file)
                
                # Filtrer par région si demandé
                if filter_by_region and selected_region != "France entière":
                    with st.spinner(f"Filtrage des données pour la région {selected_region}..."):
                        # Vérifier si une colonne 'region' ou similaire existe
                        region_cols = [col for col in gdf.columns if 'region' in col.lower() or 'reg' == col.lower()]
                        
                        if region_cols:
                            region_col = region_cols[0]
                            # Filtrage exact sur le nom de la région
                            filtered_gdf = gdf[gdf[region_col].str.contains(selected_region, case=False, na=False)]
                            
                            if len(filtered_gdf) > 0:
                                gdf = filtered_gdf
                                st.success(f"Données filtrées pour la région {selected_region}: {len(gdf)} zones trouvées")
                            else:
                                st.warning(f"Aucune zone trouvée pour la région {selected_region}. Utilisation de toutes les données.")
                        else:
                            # Essai de filtrage par bbox approximative de l'Occitanie
                            if selected_region == "Occitanie":
                                # Bbox approximative de l'Occitanie (lon_min, lat_min, lon_max, lat_max)
                                occitanie_bbox = (0.5, 42.3, 4.8, 45.0)  # Valeurs approximatives
                                
                                # S'assurer que le GDF est en WGS84
                                if gdf.crs and gdf.crs != "EPSG:4326":
                                    gdf = gdf.to_crs("EPSG:4326")
                                
                                # Créer un GeoDataFrame pour la bbox
                                from shapely.geometry import box
                                bbox_polygon = box(*occitanie_bbox)
                                
                                # Filtrer par intersection avec la bbox
                                filtered_gdf = gdf[gdf.intersects(bbox_polygon)]
                                
                                if len(filtered_gdf) > 0:
                                    gdf = filtered_gdf
                                    st.success(f"Données filtrées pour la région Occitanie par bbox: {len(gdf)} zones trouvées")
                                else:
                                    st.warning("Aucune zone trouvée dans la bbox de l'Occitanie. Utilisation de toutes les données.")
                            else:
                                st.warning(f"Impossible de filtrer automatiquement pour {selected_region}. Aucune colonne 'region' trouvée.")
                elif filter_by_region and selected_region == "France entière":
                    st.info(f"Utilisation de l'ensemble des données: {len(gdf)} zones au total pour la France entière")
                
                data_source = gdf
                file_type = "gpkg"
        except Exception as e:
            st.error(f"Erreur: Format de fichier invalide - {str(e)}")

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
                if data_source is None:
                    st.error("Veuillez d'abord charger un fichier (GeoJSON ou GPKG)")
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
                            in_aac, properties = is_in_aac(lat, lon, data_source)
                            
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
                            if file_type == "geojson":
                                for feature in data_source['features']:
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
                            elif file_type == "gpkg":
                                # Afficher un message pour informer l'utilisateur
                                with st.spinner("Chargement des zones sur la carte (cela peut prendre un moment)..."):
                                    try:
                                        # Convertir tout le GeoDataFrame en GeoJSON pour l'affichage
                                        # Simplifier les géométries pour améliorer les performances
                                        simplified_gdf = data_source.copy()
                                        
                                        # Simplification adaptative selon le nombre de zones
                                        if len(simplified_gdf) > 500:
                                            tolerance = 0.003  # Plus grande simplification pour de nombreuses zones
                                        else:
                                            tolerance = 0.001
                                            
                                        simplified_gdf['geometry'] = simplified_gdf['geometry'].simplify(tolerance=tolerance)
                                        
                                        # Convertir le CRS en WGS84 si nécessaire
                                        if simplified_gdf.crs and simplified_gdf.crs != "EPSG:4326":
                                            simplified_gdf = simplified_gdf.to_crs("EPSG:4326")
                                        
                                        # Créer un style_function qui vérifie chaque feature
                                        def style_function(feature):
                                            # Style de base
                                            style = {
                                                'fillColor': '#81C6E8',
                                                'color': '#1F75C4',
                                                'fillOpacity': 0.4,
                                                'weight': 1.5
                                            }
                                            
                                            # Vérifier si c'est la zone active
                                            if in_aac and properties:
                                                feature_props = feature['properties']
                                                # Comparer les propriétés principales (peut nécessiter des ajustements)
                                                matches = all(str(feature_props.get(k)) == str(properties.get(k)) 
                                                            for k in properties.keys() 
                                                            if k in feature_props and k != 'geometry')
                                                
                                                if matches:
                                                    style = {
                                                        'fillColor': '#4CAF50',
                                                        'color': '#2E7D32',
                                                        'fillOpacity': 0.6,
                                                        'weight': 2.5
                                                    }
                                            
                                            return style
                                        
                                        # Convertir tout le GeoDataFrame en GeoJSON puis l'ajouter à la carte
                                        geojson_data = simplified_gdf.to_json()
                                        folium.GeoJson(
                                            geojson_data,
                                            style_function=style_function
                                        ).add_to(m)
                                        
                                        # Ajuster l'emprise de la carte pour montrer toutes les zones
                                        # mais seulement si on n'est pas en train de vérifier un point spécifique
                                        if not in_aac:
                                            try:
                                                bounds = simplified_gdf.total_bounds  # [xmin, ymin, xmax, ymax]
                                                # Format pour folium: [[lat_min, lon_min], [lat_max, lon_max]]
                                                m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
                                            except:
                                                # Si ça échoue, on ne fait rien
                                                pass
                                        
                                    except Exception as e:
                                        st.error(f"Erreur lors de l'affichage des zones: {str(e)}")
                            
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
                if data_source is None:
                    st.error("Veuillez d'abord charger un fichier (GeoJSON ou GPKG)")
                else:
                    # Effacer le contenu du placeholder
                    results_placeholder.empty()
                    
                    # Recréer un conteneur pour les nouveaux résultats
                    with results_placeholder.container():
                        st.write(f"Coordonnées: {lat}, {lon}")
                        
                        # Vérification AAC
                        in_aac, properties = is_in_aac(lat, lon, data_source)
                        
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
                        if file_type == "geojson":
                            for feature in data_source['features']:
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
                        elif file_type == "gpkg":
                            # Afficher un message pour informer l'utilisateur
                            with st.spinner("Chargement des zones sur la carte (cela peut prendre un moment)..."):
                                try:
                                    # Convertir tout le GeoDataFrame en GeoJSON pour l'affichage
                                    # Simplifier les géométries pour améliorer les performances
                                    simplified_gdf = data_source.copy()
                                    
                                    # Simplification adaptative selon le nombre de zones
                                    if len(simplified_gdf) > 500:
                                        tolerance = 0.003  # Plus grande simplification pour de nombreuses zones
                                    else:
                                        tolerance = 0.001
                                        
                                    simplified_gdf['geometry'] = simplified_gdf['geometry'].simplify(tolerance=tolerance)
                                    
                                    # Convertir le CRS en WGS84 si nécessaire
                                    if simplified_gdf.crs and simplified_gdf.crs != "EPSG:4326":
                                        simplified_gdf = simplified_gdf.to_crs("EPSG:4326")
                                    
                                    # Créer un style_function qui vérifie chaque feature
                                    def style_function(feature):
                                        # Style de base
                                        style = {
                                            'fillColor': '#81C6E8',
                                            'color': '#1F75C4',
                                            'fillOpacity': 0.4,
                                            'weight': 1.5
                                        }
                                        
                                        # Vérifier si c'est la zone active
                                        if in_aac and properties:
                                            feature_props = feature['properties']
                                            # Comparer les propriétés principales (peut nécessiter des ajustements)
                                            matches = all(str(feature_props.get(k)) == str(properties.get(k)) 
                                                        for k in properties.keys() 
                                                        if k in feature_props and k != 'geometry')
                                            
                                            if matches:
                                                style = {
                                                    'fillColor': '#4CAF50',
                                                    'color': '#2E7D32',
                                                    'fillOpacity': 0.6,
                                                    'weight': 2.5
                                                }
                                        
                                        return style
                                    
                                    # Convertir tout le GeoDataFrame en GeoJSON puis l'ajouter à la carte
                                    geojson_data = simplified_gdf.to_json()
                                    folium.GeoJson(
                                        geojson_data,
                                        style_function=style_function
                                    ).add_to(m)
                                    
                                    # Ajuster l'emprise de la carte pour montrer toutes les zones
                                    # mais seulement si on n'est pas en train de vérifier un point spécifique
                                    if not in_aac:
                                        try:
                                            bounds = simplified_gdf.total_bounds  # [xmin, ymin, xmax, ymax]
                                            # Format pour folium: [[lat_min, lon_min], [lat_max, lon_max]]
                                            m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
                                        except:
                                            # Si ça échoue, on ne fait rien
                                            pass
                                    
                                except Exception as e:
                                    st.error(f"Erreur lors de l'affichage des zones: {str(e)}")
                        
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
        Aire d'Alimentation de Captage (AAC). Supporte les fichiers GeoJSON et GeoPackage (GPKG).""")
