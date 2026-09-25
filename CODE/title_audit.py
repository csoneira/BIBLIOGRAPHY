#!/usr/bin/env python3
"""Build a resumable Crossref title-audit cache without changing metadata."""

import argparse
import csv
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

APPLICATION_ROOT = Path(__file__).resolve().parent.parent
CODE_ROOT = Path(__file__).resolve().parent
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))
from library_state import resolve_library_selection

LIBRARY_ROOT = resolve_library_selection(APPLICATION_ROOT)["root"]
ROOT = LIBRARY_ROOT  # Backward-compatible alias.
METADATA_FILE = LIBRARY_ROOT / "METADATA" / "metadata.csv"
CACHE_FILE = LIBRARY_ROOT / "METADATA" / "title_audit_cache.json"
USER_AGENT = "BIBLIOGRAPHY-title-audit/1.0 (mailto:csoneira@ucm.es)"

# Corrections established from document title pages, repository history, or an
# authoritative catalogue/publisher record.  This deliberately excludes guesses:
# entries that still need their remote PDF remain unchanged in the review report.
MANUAL_TITLES = {
    "1999_article_measurements_of_ground_level_muons_at_two_geomagnetic_locati":
        "Measurements of Ground-Level Muons at Two Geomagnetic Locations",
    "2000_article_a_new_high_resolution_tof_technology": "A New High-Resolution TOF Technology",
    "2000_article_introduccio_n_a_r_notas_sobre_r_un_entorno_de_programacio_n":
        "Introducción a R: Notas sobre R, un entorno de programación para análisis de datos y gráficos",
    "2001_article_the_day_night_variation_of_cosmic_rays_intensity":
        "The day-night variation of cosmic ray intensity",
    "2002_article_a_oximati_ns_to_multiple_coulomb_scattering":
        "Approximations to Multiple Coulomb Scattering",
    "2002_book_a_thin_cosmic_rain": "A Thin Cosmic Rain",
    "2000_book_aprenda_linux_como_si_estuviera_en_primero":
        "Aprenda Linux como si estuviera en primero",
    "2001_article_an_accurate_measurement_of_the_sea_level_muon_spectrum_withi":
        "An Accurate Measurement of the Sea-Level Muon Spectrum Within the Range 4 to 3000 GeV/c",
    "2002_article_measurements_the_best_fit_differential_and_integral_intensit":
        "The Absolute Cosmic-Ray Muon Spectrum at Sea Level",
    "2004_article_cosmic_ray_muon_observation_at_southern_space_observatory_x2":
        "Cosmic Ray Muon Observation at Southern Space Observatory—SSO (29°S, 53°W)",
    "2004_article_forbush_decreases_in_the_cosmic_radiation":
        "Forbush Decreases in the Cosmic Radiation",
    "2004_article_john_wlley_sons_new_york_chichester_brisbane_toronto_singapo":
        "Introductory Nuclear Physics",
    "2004_book_john_wlley_sons_new_york_chichester_brisbane_toronto_singapo":
        "Introductory Nuclear Physics",
    "2005_book_physics_of_atoms_and_molecules": "Physics of Atoms and Molecules",
    "2005_book_circuitos_microelectr_nicos": "Circuitos microelectrónicos",
    "2006_book_and_methods_nonlinear_programming": "Optimization Theory and Methods",
    "2007_book_cosmic_rays_at_earth":
        "Cosmic Rays at Earth: Researcher's Reference Manual and Data Book",
    "2007_book_sakurai_modern_quantum_mechanics_djvu": "Modern Quantum Mechanics",
    "2007_book_statistical_mechanics_algorithms_and_computations_oxford_mas":
        "Statistical Mechanics: Algorithms and Computations",
    "2008_book_modern_optics": "Modern Optics",
    "2008_article_first_spaceweather_observations_at_mustang_the_muon_spacewea":
        "First Space-Weather Observations at MuSTAnG: The Muon Spaceweather Telescope for Anisotropies at Greifswald",
    "2008_book_solving_ordinary_differential":
        "Solving Ordinary Differential Equations I: Nonstiff Problems",
    "2009_article_particle_physics": "Particle Physics",
    "2009_article_ground_based_cosmic_ray_instrumentation_catalog":
        "Ground-Based Cosmic-Ray Instrumentation Catalog",
    "2009_article_zenith_angle_response_of_a_vertical_meson_telescope":
        "Zenith Angle Response of a Vertical Meson Telescope",
    "2009_book_solid_state_physics_an_introduction_to_principles_of_materia":
        "Solid State Physics: An Introduction to Principles of Materials Science",
    "2009_article_microsoft_word_revista_i_encuentro_divulgacion_doc":
        "Imagen médica mediante tomografía por emisión de positrones (PET)",
    "2010_article_18_experimental_tests_of_gravitational_theory_225":
        "Experimental Tests of Gravitational Theory",
    "2010_article_cosmic_ray_muons_in_the_deep_ocean": "Cosmic-Ray Muons in the Deep Ocean",
    "2010_article_e_submission_file_reference_temp":
        "Precursors of the Forbush Decrease on 2006 December 14 Observed with the Global Muon Detector Network (GMDN)",
    "2010_book_fundamentos_de_circuitos_electricos": "Fundamentos de circuitos eléctricos",
    "2010_book_introduction_to_quantum_mechanics": "Introduction to Quantum Mechanics",
    "2010_thesis_determination_of_the_angular_distribution_of_cosmic_rays_at":
        "Determination of the Angular Distribution of Cosmic Rays at Sea Level",
    "2011_article_experimental_test_of_parity_conservation_in_beta_decay":
        "Experimental Test of Parity Conservation in Beta Decay",
    "2011_book_air_showers_high_energy_phenomena":
        "Extensive Air Showers: High Energy Phenomena and Astrophysical Aspects",
    "2012_article_cosmicrayrpp": "Cosmic Rays",
    "2012_thesis_analysis_of_the_one_cosmic_ray":
        "Analysis of the One-Cosmic-Ray Events Taken During the Commissioning of the HADES RPC Wall at GSI: First Results",
    "2012_article_introduction_to_elementary_particles_2nd_edition":
        "Introduction to Elementary Particles",
    "2013_book_a_geometric_approach_to_differential_forms":
        "A Geometric Approach to Differential Forms",
    "2012_thesis_new_advances_and_developments_on_the_rpc_tof_wall_of_the_had":
        "New Advances and Developments on the RPC TOF Wall of the HADES Experiment at GSI",
    "2013_article_data_and_information_activities_of_serc_kyushu_university_ja":
        "Data and Information Activities of ICSWSE, Kyushu University, Japan",
    "2013_article_physics_of_the_solar_cycle_new_views":
        "Geomagnetic Effects on Cosmic-Ray Propagation Under Different Conditions for Buenos Aires and Marambio, Argentina",
    "2013_article_lectures_on_quantum_mechanics": "Lectures on Quantum Mechanics",
    "2013_book_springer_series_in_computational":
        "ISO 15930: Electronic Document File Format for Prepress Digital Data Exchange (PDF/X)",
    "2013_book_numerical_optimization": "Numerical Optimization",
    "2013_slides_introduction_to_the_micropattern":
        "Introduction to the Micropattern Gaseous Detectors",
    "2013_slides_flavio_loddo_istituto_nazionale_di_fisica_nucleare_sez_di_ba":
        "Front-End Electronics",
    "2014_book_quantum_field_theory_for_the_gifted":
        "Quantum Field Theory for the Gifted Amateur",
    "2014_book_radiation_detection_and_measurement": "Radiation Detection and Measurement",
    "2015_article_programa_de_fi_sica_nuclear": "Programa de Física Nuclear",
    "2015_article_introducci_n_al_lenguaje_python": "Introducción al lenguaje Python (2.7)",
    "2015_article_introducci_n_al_lenguaje_python_2": "Introducción al lenguaje Python (2.7)",
    "2015_book_f_sica_nuclear_y_de_part_culas": "Física Nuclear y de Partículas",
    "2016_article_the_pierre_auger_observatory_upgrade": "The Pierre Auger Observatory Upgrade",
    "2016_book_gravitation": "Gravitation",
    "2017_article_griffiths_quantum": "Introduction to Quantum Mechanics",
    "2017_article_kittel_introducci_n_a_la_f_sica_del_estado_s_li":
        "Introducción a la Física del Estado Sólido",
    "2017_book_curso_de_astronomia_abad_correcto": "Curso de Astronomía",
    "2017_book_graduate_texts_in_physics":
        "Computational Physics: Simulation of Classical and Quantum Systems",
    "2017_article_tragaldabas_first_results_on_cosmic_ray_studies_and_their_re":
        "TRAGALDABAS: First Results on Cosmic-Ray Studies and Their Relation with Solar Activity, Earth's Magnetic Field, and Atmospheric Properties",
    "2017_slides_in_vivo_and_in_beam_monitoring_of_pet":
        "In Vivo and In-Beam Monitoring with PET",
    "2018_article_maza_2008_f_sica_del_estado_s_lido": "Física del Estado Sólido",
    "2018_slides_aplicaciones_pptx": "Aplicaciones de la Física Nuclear y de Partículas",
    "2018_book_resistive_gaseous_detectors": "Resistive Gaseous Detectors",
    "2018_thesis_simulation_and_reconstruction_algorithms_for_a_commercial_mu":
        "Simulation and Reconstruction Algorithms for a Commercial Muon Tomography System",
    "2019_article_1_29_cosmic_rays_29_cosmic_rays": "Cosmic Rays",
    "2019_article_recent_results_of_cosmic_ray_measurements_from_icecube_and_i":
        "Recent Results of Cosmic Ray Measurements from IceCube and IceTop",
    "2019_article_seasonal_variation_of_atmospheric_muons_in_icecube":
        "Seasonal Variation of Atmospheric Muons in IceCube",
    "2019_article_atmospheric_variations_as_observed_by_icecube":
        "Atmospheric Variations as Observed by IceCube",
    "2019_book_classical_dynamics_a_contemporary_approa":
        "Classical Dynamics: A Contemporary Approach",
    "2019_thesis_studies_on_the_composition_and_energy_of_secondary_cosmic_ra":
        "Studies on the Composition and Energy of Secondary Cosmic Rays with the TRAGALDABAS Detector",
    "2020_notes_1_curvas_no_espazo_eucl_deo_3_dimensional":
        "Curvas no espazo euclídeo tridimensional",
    "2020_notes_1_introducci_n_a_la_inferencia_estad_stica":
        "Introducción a la inferencia estadística",
    "2020_article_lectures_on_quantum_theory_chris_isham":
        "Lectures on Quantum Theory",
    "2020_article_weissbluth_atoms_molecules": "Atoms and Molecules",
    "2020_book_introduction_to_smooth_manifolds_second_edition":
        "Introduction to Smooth Manifolds",
    "2021_article_cosmic_ray_spectrum_and_composition_from_pev_to_eev_from_the":
        "Cosmic Ray Spectrum and Composition from PeV to EeV from the IceCube Neutrino Observatory",
    "2021_article_apuntes_de_la_asignatura": "Teoría de juegos",
    "2021_article_xxii_international_workshop_on_radiation_imaging_detectors_i":
        "A Portable Muon Telescope for Multidisciplinary Applications",
    "2021_article_mu_11a_f_sica_del_estado_s_lido": "Física del Estado Sólido",
    "2021_article_luis_miguel_varela_departamento_de_f_sica_de_la_materia_cond":
        "Mecánica Estadística",
    "2021_article_on_the_visualisation_of_differential_forms":
        "On the Visualisation of Differential Forms",
    "2021_article_zenith_angle_dependence_of_pressure_effect_in_grapes_3":
        "Zenith-Angle Dependence of the Pressure Effect in the GRAPES-3 Muon Telescope",
    "2021_article_jos_antonio_oubi_a_gali_anes": "Variedades Diferenciables",
    "2021_slides_i_ns_s_20_21_aug_us_t_5_t_h_t_hu_s":
        "Physics with Water Cherenkov Detector",
    "2022_article_about_the_necessity_to_build_new_polar_neutron_monitor":
        "About the Necessity to Build New Polar Neutron Monitor Stations",
    "2022_article_la_geometr_a_de_la_variable_compleja":
        "La geometría de la variable compleja",
    "2022_book_gaseous_detectors_handbook": "Gaseous Detectors Handbook",
    "2021_thesis_a_scintillating_experiment": "A Scintillating Experiment",
    "2022_thesis_interactions_between_cosmic_rays_and_the_atmosphere_modeling":
        "Interactions Between Cosmic Rays and the Atmosphere: Modeling and Practical Applications",
    "2022_thesis_cosmic_rays_study_with_a_trasgo_detector":
        "Cosmic-Ray Studies with a TRASGO Detector",
    "2022_thesis_study_of_cosmic_ray_data_with_the_tristan_and_tragaldabas_de":
        "Study of Cosmic-Ray Data with the TRISTAN and TRAGALDABAS Detection Systems",
    "2023_article_he_o_all_particle_knee": "Cosmic Rays",
    "2023_article_fuente_de_calibraci_n_embarcada_en":
        "Fuente de calibración embarcada en satélite para experimentos del fondo cósmico de microondas desde tierra",
    "2023_article_fuente_de_calibraci_n_embarcada_en_sat_lite_para_experimento":
        "Fuente de calibración embarcada en satélite para experimentos del fondo cósmico de microondas desde tierra",
    "2023_article_laboratorio_de_f_sica_nuclear_y_de_part_culas":
        "Laboratorio de Física Nuclear y de Partículas",
    "2023_article_laboratorio_de_f_sica_nuclear_y_de_part_culas_2":
        "Laboratorio de Física Nuclear y de Partículas",
    "2023_slides_astronom_a_de_multimensajeros": "Astronomía de Multimensajeros",
    "2023_article_tomograf_a_por_emisi_n_de_positrones":
        "Tomografía por Emisión de Positrones",
    "2023_book_diego_herranz_enrique_mart_nez_gonza_lez": "Cosmology",
    "2023_slides_on_the_fly_reconstruction_of_activation_by_proton_beams_usin":
        "On-the-Fly Reconstruction of Activation by Proton Beams Using In-Beam PET",
    "2023_slides_on_the_fly_reconstruction_of_activation_by_proton_beams_usin_2":
        "On-the-Fly Reconstruction of Activation by Proton Beams Using In-Beam PET",
    "2024_article_international_cosmic_ray_conference_1985_paper_3_434l":
        "Mini and Super Mini Arrays for the Study of Highest Energy Cosmic Rays",
    "2024_article_resistive_plate_chambers_are_used_in_the_atlas_experiment_fo":
        "Performance of ATLAS RPC Detectors and L1 Muon Barrel Trigger with a New CO2-Based Gas Mixture",
    "2024_article_stability_studies_of_sealed_resistive_plate_chambers":
        "Stability Studies of Sealed (Zero Gas Flow) Resistive Plate Chambers",
    "2024_book_the_28th_european_cosmic":
        "The 28th European Cosmic Ray Symposium (ECRS 2024)",
    "2024_article_a_simple_parameterization_of_the_cosmic_ray":
        "A Simple Parameterization of the Cosmic-Ray Muon Momentum Spectra at the Surface as a Function of Zenith Angle",
    "2024_slides_enhancing_compton_camera_imaging":
        "Enhancing Compton Camera Imaging with Neural Networks",
    "2024_slides_isvhecri_eas_neutrons_engel_2024_v1":
        "Neutron Production in Simulations of Extensive Air Showers",
    "2024_slides_los_rayos_c_smicos_y_la_atm_sfera":
        "Los rayos cósmicos y la atmósfera",
    "2024_slides_trasgo_detectors_expected_secondary_cosmic_rays_at_di_erent":
        "TRASGO Detectors: Expected Secondary Cosmic Rays at Different Locations and Primary Cosmic-Ray Incident Angles",
    "2024_slides_timing_properties_in_resistive_plate":
        "Timing Properties in Resistive Plate Chambers from Statistical Considerations",
    "2024_slides_research_and_development_of_micro_pixel_multilayer_charge":
        "Research and Development of Micro-Pixel Multilayer Charge-Sharing Micromegas Detectors",
    "2025_article_data_publication_activities_for_the_global_muon":
        "Data Publication Activities for the Global Muon Detector Network (GMDN)",
    "2025_article_long_term_evolution_of_cosmic_ray_modulation_a_comprehensive":
        "Long-Term Evolution of Cosmic Ray Modulation: A Comprehensive Analysis of Solar and Heliospheric Influences (1964–2024)",
    "2025_article_measurement_of_the_muon_flux_at_the_lhc_using_the_srpc_detec":
        "Measurement of the Muon Flux at the LHC Using the sRPC Detector",
    "2025_article_monolithic_plastic_scintillator_detectors_novel_concepts_and":
        "Monolithic Plastic Scintillator Detectors: Novel Concepts and Frontier Developments",
    "2025_article_monolithic_scintillator_detectors_read_out_by_sipm_arrays_st":
        "Monolithic Scintillator Detectors Read Out by SiPM Arrays: State of the Art",
    "2025_article_monolithic_vs_segmented_scintillator_detectors_in_modern_exp":
        "Monolithic vs. Segmented Scintillator Detectors in Modern Experiments",
    "2025_article_muon_tracker_with_unsegmented_plastic_scintillator_panels":
        "Muon Tracker with Unsegmented Plastic Scintillator Panels",
    "2025_article_performance_study_of_a_position_sensitive_plastic_scintillat":
        "Performance Study of a Position-Sensitive Plastic Scintillator Detector",
    "2025_article_scaler_rates_from_the_pierre_auger_observatory":
        "Scaler Rates from the Pierre Auger Observatory: A New Proxy of Solar Activity",
    "2025_article_rigidity_spectrum_of_cosmic_ray_anisotropy":
        "Rigidity Spectrum of Cosmic-Ray Anisotropy Observed by the Global Muon Detector Network (GMDN)",
    "2025_article_spectra_and_anisotropy_during_gle_74_on_11_may":
        "Spectra and Anisotropy During GLE 74 on 11 May 2024 Derived Using Neutron Monitor Data",
    "2025_article_time_of_flight_detector_for_the_identification_of_low_moment":
        "Time-of-Flight Detector for the Identification of Low-Momentum Secondary Cosmic Rays in the ACROMASS Experiment",
    "2025_poster_response_of_galactic_cosmic_rays_to_solar":
        "Response of Galactic Cosmic Rays to Solar Activity",
    "2025_preprint_a_compact_two_dimensional_radiation_detector_for_educational":
        "A Compact Two-Dimensional Radiation Detector for Educational Applications",
    "2025_preprint_commissioning_of_proanubis_a_proof_of_concept_detector_for_t":
        "Commissioning of proANUBIS: A Proof-of-Concept Detector for the ANUBIS Experiment",
    "2025_preprint_development_and_testing_of_a_modular_large_area_cosmic_ray_t":
        "Development and Testing of a Modular Large-Area Cosmic-Ray Telescope Using a Scintillator-Fiber Hybrid Design for Millimeter-Level Muon Tracking",
    "2025_preprint_enhancing_air_shower_observations_results_from_an_icecube_su":
        "Enhancing Air-Shower Observations: Results from an IceCube Surface-Array Prototype Station",
    "2025_preprint_feyncraft_a_game_of_feynman_diagrams":
        "FeynCraft: A Game of Feynman Diagrams",
    "2025_preprint_improving_muon_scattering_tomography_performance_with_a_muon":
        "Improving Muon Scattering Tomography Performance with a Muon Momentum Measurement Scheme",
    "2025_preprint_millimeter_resolution_cosmic_ray_imaging_via_projection_shif":
        "Millimeter-Resolution Cosmic-Ray Imaging via Projection-Shifted Muon Transmission Tomography",
    "2025_preprint_multiplexed_sipm_readout_of_plastic_scintillating_fiber_dete":
        "Multiplexed SiPM Readout of a Plastic Scintillating-Fiber Detector for Muon Tomography",
    "2025_preprint_science_prospects_for_the_southern_wide_field_gamma_ray_obse":
        "Science Prospects for the Southern Wide-Field Gamma-Ray Observatory (SWGO)",
    "2025_preprint_updated_earth_tomography_using_atmospheric_neutrinos_at_icec":
        "Updated Earth Tomography Using Atmospheric Neutrinos at IceCube",
    "2025_preprint_performance_reconstruction_of_eco_friendly_gas_mixtures_for":
        "Performance Reconstruction of Eco-Friendly Gas Mixtures for Improved Resistive Plate Chambers at GIF++ Using Geant4",
    "2025_preprint_using_cosmic_rays_to_predict_the_weather_meteorological_data":
        "Using Cosmic Rays to Improve Weather Forecasting: Meteorological Data Assimilation of Atmospheric Muon Flux Data",
    "2025_slides_powerpoint_presentation":
        "Site-Specific Incoming Correction Based on Muons: A Comparison with Cosmic-Neutron Measurements at JUNG and OULU",
    "2025_thesis_analysing_the_impact_of_detector":
        "Analysing the Impact of Detector Properties on Pulse Shape Discrimination in Plastic Scintillation Detectors Using Monte Carlo Simulations",
    "2026_article_analysis_of_solar_activities_on_cosmic_muon_flux_using_a_por":
        "Analysis of Solar Activities on Cosmic Muon Flux Using a Portable Muon Telescope in Agra",
    "2026_article_scintillation_muon_telescope_module_with_fiber_optic_light_c":
        "Scintillation Muon Telescope Module with Fiber-Optic Light Collection",
    "2026_article_study_of_electrode_property_of_resistive_plate_chamber":
        "Study of Electrode Properties of a Resistive Plate Chamber",
    "2026_article_thunderstorm_induced_variations_in_ground_level":
        "Thunderstorm-Induced Variations in Ground-Level Cosmic-Muon Measurements: State-of-the-Art Review of Ground-Based Observations (as of February 2026)",
    "2026_preprint_ground_level_enhancement_gle_77_in_the_gamma_ray_component_f":
        "Ground-Level Enhancement (GLE #77) in the Gamma-Ray Component: First Observation from Arctic and Antarctic Stations",
    "2026_preprint_monitoring_the_upper_atmospheric_temperature_and_interplanet":
        "Monitoring the Upper Atmospheric Temperature and Interplanetary Magnetic Field with the GRAPES-3 Muon Telescope",
    "2026_thesis_atmospheric_muon_flux_study_with_gem_detectors":
        "Atmospheric Muon Flux Study with GEM Detectors",
    "2026_preprint_the_muon_charge_asymmetry_and_the_directional_distribution_o":
        "The Muon Charge Asymmetry and the Directional Distribution of Thunderstorm Events Observed by the GRAPES-3 Muon Telescope",
    "2026_article_a_galactic_cosmic_ray_cavity_in_earth_moon_space":
        "A Galactic Cosmic-Ray Cavity in Earth-Moon Space",
    "2009_thesis_design_and_characterisation_studies_of_resistive_plate_chamb":
        "Design and Characterisation Studies of Resistive Plate Chambers",
    "2021_article_performance_of_the_msmgrpc_with_the_highest_granularity_of_t":
        "Performance of the MSMGRPC with the Highest Granularity of the CBM-TOF Wall in Cosmic-Ray Tests",
    "2026_slides_sealed_rpcs_status_and_perspectives": "Sealed RPCs: Status and Perspectives",
}

NEEDS_REMOTE_PDF = {
    "2018_article_universidad_complutense_de_madrid",
    "2022_article_facultade_de_f_sica_grao_en_f_sica",
}

DOI_TITLE_OVERRIDES = {
    "10.1016/j.nima.2023.168384":
        "Development and performance studies of a real size Resistive Plate Chamber tested at GIF++, CERN for CBM-MuCh at FAIR, Germany",
    "10.1016/j.nima.2010.09.133":
        "RPC simulation in avalanche and streamer modes using transport equations for electrons and ions",
    "10.3847/0004-637X/830/2/88":
        "The Temperature Effect in Secondary Cosmic Rays (Muons) Observed at the Ground: Analysis of the Global Muon Detector Network Data",
    "10.1029/2020EA001131":
        "Atmospheric Temperature Effect in Secondary Cosmic Rays Observed with a 2 m² Ground-Based tRPC Detector",
    "10.1140/epjc/s10052-020-8055-y":
        "Direct Measurement of the Muonic Content of Extensive Air Showers Between 2 × 10^17 and 2 × 10^18 eV at the Pierre Auger Observatory",
    "10.1016/j.ppnp.2024.104152":
        "γ–γ Fast Timing with High-Performance LaBr3(Ce) Scintillators",
    "10.1140/epja/i2017-12248-y":
        "Challenges in QCD Matter Physics — The Scientific Programme of the Compressed Baryonic Matter Experiment at FAIR",
}


def clean_markup(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def comparison_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalize_doi(value: str) -> str:
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(value or "").strip(), flags=re.I)
    return re.sub(r"^doi:\s*", "", value, flags=re.I)


def publication_year(message: dict) -> str:
    for field in ("published-print", "published-online", "issued", "created"):
        parts = message.get(field, {}).get("date-parts", [])
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def crossref_request(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))["message"]


def candidate_from_message(message: dict, current_title: str, row: dict) -> dict:
    title = clean_markup((message.get("title") or [""])[0])
    authors = []
    for author in message.get("author", []):
        name = " ".join(filter(None, [author.get("given", ""), author.get("family", "")])).strip()
        if name:
            authors.append(name)
    author_tokens = [token for token in comparison_key(row.get("author", "")).split() if len(token) > 2]
    candidate_author_key = comparison_key("; ".join(authors))
    return {
        "title": title,
        "doi": message.get("DOI", ""),
        "year": publication_year(message),
        "authors": "; ".join(authors),
        "journal": clean_markup((message.get("container-title") or [""])[0]),
        "type": message.get("type", ""),
        "crossref_score": message.get("score"),
        "title_similarity": round(
            SequenceMatcher(None, comparison_key(current_title), comparison_key(title)).ratio(), 3
        ),
        "year_match": bool(row.get("year") and publication_year(message) == row.get("year")),
        "author_match": bool(
            author_tokens and any(token in candidate_author_key for token in author_tokens)
        ),
        "source_url": message.get("URL", ""),
    }


def audit_row(row: dict) -> dict:
    current_title = row.get("title", "")
    doi = normalize_doi(row.get("doi", ""))
    if doi:
        message = crossref_request(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        return {
            "method": "doi",
            "current": current_title,
            "candidates": [candidate_from_message(message, current_title, row)],
        }

    query = " ".join(
        value.strip()
        for value in (current_title, row.get("author", ""), row.get("year", ""))
        if value and value.strip()
    )
    params = urlencode(
        {
            "query.bibliographic": query,
            "rows": 5,
            "select": (
                "DOI,title,author,published-print,published-online,issued,created,"
                "container-title,type,score,URL"
            ),
            "mailto": "csoneira@ucm.es",
        }
    )
    message = crossref_request(f"https://api.crossref.org/works?{params}")
    return {
        "method": "bibliographic-search",
        "current": current_title,
        "query": query,
        "candidates": [
            candidate_from_message(candidate, current_title, row)
            for candidate in message.get("items", [])
        ],
    }


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"entries": {}}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": {}}
    data.setdefault("entries", {})
    return data


def save_cache(cache: dict) -> None:
    cache["updated_at"] = datetime.now(timezone.utc).isoformat()
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=CACHE_FILE.parent, prefix=".title-audit-", suffix=".tmp",
        delete=False, encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(cache, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temp_path, CACHE_FILE)


def preferred_title(row: dict, cached: dict) -> tuple[str, str, str]:
    """Return (title, decision, source) for a previously audited row."""
    code = row.get("code", "")
    if code in NEEDS_REMOTE_PDF:
        return row.get("title", ""), "needs_remote_pdf", "title page required from naranjito PDF"
    if code in MANUAL_TITLES:
        return MANUAL_TITLES[code], "corrected", "manual verification"

    doi = normalize_doi(row.get("doi", ""))
    if doi in DOI_TITLE_OVERRIDES:
        return DOI_TITLE_OVERRIDES[doi], "corrected", f"DOI {doi}"

    candidates = cached.get("candidates") or []
    if doi and candidates and candidates[0].get("title"):
        return candidates[0]["title"].replace("GIF＋＋", "GIF++"), "corrected", f"DOI {doi}"

    if candidates:
        candidate = candidates[0]
        # A bibliographic search is accepted automatically only when the title
        # words are identical and at least one independent field agrees.
        if (
            candidate.get("title")
            and candidate.get("title_similarity", 0) >= 0.995
            and (candidate.get("year_match") or candidate.get("author_match"))
        ):
            return candidate["title"], "corrected", candidate.get("source_url", "Crossref search")

    if cached.get("error"):
        return row.get("title", ""), "needs_remote_pdf", cached["error"]
    return row.get("title", ""), "reviewed_unchanged", "no authoritative replacement found"


def export_review(rows: list[dict], cache: dict, apply_changes: bool) -> dict:
    review_path = ROOT / "METADATA" / "title_review.csv"
    review_fields = ("code", "old_title", "reviewed_title", "decision", "source")
    previous = {}
    if review_path.exists():
        with review_path.open(encoding="utf-8", newline="") as handle:
            previous = {item["code"]: item for item in csv.DictReader(handle)}
    changed = 0
    unresolved = 0
    review_rows = []
    for row in rows:
        cached = cache["entries"].get(row.get("code", ""), {})
        old_title = previous.get(row.get("code", ""), {}).get("old_title", row.get("title", ""))
        audit_row = dict(row)
        audit_row["title"] = old_title
        title, decision, source = preferred_title(audit_row, cached)
        if title != old_title:
            changed += 1
        elif decision == "corrected":
            decision = "verified"
        if decision == "needs_remote_pdf":
            unresolved += 1
        review_rows.append({
            "code": row.get("code", ""),
            "old_title": old_title,
            "reviewed_title": title,
            "decision": decision,
            "source": source,
        })
        if apply_changes:
            row["title"] = title

    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(review_rows)

    if apply_changes:
        with tempfile.NamedTemporaryFile(
            "w", dir=METADATA_FILE.parent, prefix=".metadata-title-audit-",
            suffix=".tmp", delete=False, encoding="utf-8", newline="",
        ) as handle:
            temp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, METADATA_FILE)

    return {"reviewed": len(rows), "changed": changed, "needs_remote_pdf": unresolved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "doi", "search"), default="all")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--export-review", action="store_true")
    parser.add_argument("--apply", action="store_true", help="apply reviewed titles to metadata.csv")
    args = parser.parse_args()

    with METADATA_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    cache = load_cache()
    if args.apply:
        args.export_review = True
    if args.export_review:
        result = export_review(rows, cache, args.apply)
        print(json.dumps(result))
        return 0
    completed = 0
    skipped = 0
    errors = 0

    for index, row in enumerate(rows, 1):
        has_doi = bool(normalize_doi(row.get("doi", "")))
        if args.mode == "doi" and not has_doi or args.mode == "search" and has_doi:
            continue
        code = row.get("code", "")
        cached = cache["entries"].get(code, {})
        same_input = cached.get("current") == row.get("title", "")
        if same_input and ("error" not in cached or not args.retry_errors):
            skipped += 1
            continue
        try:
            result = audit_row(row)
            result.update({"index": index, "year": row.get("year", ""), "author": row.get("author", "")})
            cache["entries"][code] = result
            completed += 1
        except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            cache["entries"][code] = {
                "index": index,
                "year": row.get("year", ""),
                "author": row.get("author", ""),
                "current": row.get("title", ""),
                "method": "doi" if has_doi else "bibliographic-search",
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors += 1
        save_cache(cache)
        print(f"[{index:03}/{len(rows)}] {code}: {'error' if 'error' in cache['entries'][code] else 'ok'}", flush=True)
        time.sleep(0.08)

    print(json.dumps({"completed": completed, "skipped": skipped, "errors": errors}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
