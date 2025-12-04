from skyfield.api import load, wgs84
from skyfield.sgp4lib import EarthSatellite
import numpy as np
import random
import json
from astropy import units as u
from astropy.time import Time
from poliastro.bodies import Earth
from poliastro.twobody import Orbit
from poliastro.maneuver import Maneuver

# --- CONFIGURATION ---
SCENARIO_NAME = "SENTINEL: DEEP SPACE MONITOR"
DURATION_HOURS = 24
STEP_MINUTES = 2
COLLISION_THRESHOLD_KM = 200.0
MANEUVER_LEAD_TIME_MIN = 45

# --- ASSETS TO TRACK ---
ASSETS = [
    {'name': 'ISS (ZARYA)', 'id': 'iss', 'catnr': '25544'},
    {'name': 'HST (HUBBLE)', 'id': 'hubble', 'catnr': '20580'},
    {'name': 'SENTINEL-6', 'id': 'sentinel', 'catnr': '46984'}
]

# Global cache for loaded data
_data_cache = {
    'fleet': None,
    'debris': None,
    'ts': None
}

def get_url(catnr):
    return f'https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle'

def load_data():
    """Loads TLE data once and caches it."""
    if _data_cache['fleet'] is not None:
        return _data_cache['ts'], _data_cache['fleet'], _data_cache['debris']

    print("[SYSTEM] Initializing Orbital Dynamics Engine...")
    ts = load.timescale()
    
    print("  - Loading Fleet Ephemeris...")
    fleet = []
    for asset in ASSETS:
        try:
            try:
                sat = load.tle_file(f"{asset['id']}.tle")[0]
            except:
                sat = load.tle_file(get_url(asset['catnr']), filename=f"{asset['id']}.tle")[0]
            # Note: We store a mutable dictionary for maneuver/collisions, 
            # but for a fresh simulation we need to reset those fields.
            # So we store just the static data here.
            fleet.append({'data': asset, 'sat': sat})
        except Exception as e:
            print(f"    ! Failed to load {asset['name']}: {e}")

    print("  - Loading Debris Fields...")
    try:
        debris_iridium = load.tle_file('debris_iridium.tle')
        debris_cosmos = load.tle_file('debris_cosmos.tle')
        real_debris = debris_iridium + debris_cosmos
        if len(real_debris) > 1200:
            real_debris = random.sample(real_debris, 1200)
    except Exception as e:
        print("    ! Using synthetic debris fallback.")
        real_debris = []
    
    _data_cache['ts'] = ts
    _data_cache['fleet'] = fleet
    _data_cache['debris'] = real_debris
    
    return ts, fleet, real_debris

def get_czml():
    """Runs the simulation and returns the CZML structure."""
    ts, static_fleet, real_debris = load_data()
    
    print(f"    > Tracking {len(static_fleet)} Assets vs {len(real_debris)} Debris Objects.")

    # Create a fresh fleet list for this simulation run so we don't persist maneuvers across refreshes
    fleet = []
    for item in static_fleet:
        fleet.append({
            'data': item['data'], 
            'sat': item['sat'], 
            'maneuver': None, 
            'collisions': []
        })

    # --- SIMULATION SETUP ---
    start_time = ts.now()
    steps = int(DURATION_HOURS * 60 / STEP_MINUTES)
    times = [start_time + (i * STEP_MINUTES / 1440.0) for i in range(steps)]

    # --- COLLISION DETECTION & MANEUVER PLANNING ---
    print(f"[SYSTEM] Running Propagations ({DURATION_HOURS}h window)...")

    threat_debris_ids = set()

    for asset_obj in fleet:
        sat = asset_obj['sat']
        name = asset_obj['data']['name']
        
        detected_risk = None
        
        for t_idx in range(0, len(times), 5):
            t = times[t_idx]
            my_pos = sat.at(t).position.km
            
            for deb in real_debris:
                deb_pos = deb.at(t).position.km
                dist = np.linalg.norm(my_pos - deb_pos)
                
                if dist < COLLISION_THRESHOLD_KM:
                    detected_risk = {'time': t, 'debris': deb, 'dist': dist}
                    threat_debris_ids.add(deb.model.satnum)
                    break
            if detected_risk:
                break
        
        if detected_risk:
            print(f"  ! ALERT: {name} collision risk with {detected_risk['debris'].name} ({detected_risk['dist']:.1f}km)")
            
            burn_time = detected_risk['time'] - (MANEUVER_LEAD_TIME_MIN / 1440.0)
            if burn_time < start_time: burn_time = start_time
            
            pos_vec = sat.at(burn_time).position.km * u.km
            vel_vec = sat.at(burn_time).velocity.km_per_s * u.km / u.s
            
            epoch_astropy = Time(burn_time.utc_datetime())
            orbit_initial = Orbit.from_vectors(Earth, pos_vec, vel_vec, epoch=epoch_astropy)
            
            dv = 0.008 * u.km / u.s
            v_norm = np.linalg.norm(orbit_initial.v.value)
            impulse = dv * (orbit_initial.v / (v_norm * u.km/u.s))
            
            maneuver = Maneuver.impulse(impulse)
            orbit_new = orbit_initial.apply_maneuver(maneuver)
            
            asset_obj['maneuver'] = {
                'time': burn_time,
                'orbit_new': orbit_new,
                'risk': detected_risk,
                'type': 'PROGRADE AVOIDANCE'
            }

    # --- CZML GENERATION ---
    print("[SYSTEM] Generating Telemetry (CZML)...")

    czml = [{
        "id": "document",
        "name": SCENARIO_NAME,
        "version": "1.0",
        "clock": {
            "interval": f"{times[0].utc_iso()}/{times[-1].utc_iso()}",
            "currentTime": times[0].utc_iso(),
            "multiplier": 60, 
            "range": "LOOP_STOP",
            "step": "SYSTEM_CLOCK_MULTIPLIER"
        }
    },
    {
        "id": "earth_center",
        "name": "Earth Center",
        "position": {"cartesian": [0.0, 0.0, 0.0]}
    }]

    epoch = times[0]

    # 1. Render Assets (With Composite Model)
    for asset in fleet:
        sat = asset['sat']
        maneuver = asset['maneuver']
        
        # Calculate Orbital Elements for Display
        inclination_deg = sat.model.inclo * 180.0 / np.pi
        period_min = 2 * np.pi / sat.model.no_kozai
        eccentricity = sat.model.ecco
        
        status_html = '<span style="color:#ff3333; font-weight:bold;">⚠ EVASIVE MANEUVER</span>' if maneuver else '<span style="color:#00ff66; font-weight:bold;">NOMINAL OPERATION</span>'
        
        description = f"""
        <div style="font-family: 'Roboto Mono', monospace; font-size: 12px; text-align: left; color: #e0e0e0;">
            <h3 style="margin: 0 0 5px 0; color: #00f2ff; border-bottom: 1px solid #00f2ff; padding-bottom: 3px;">{asset['data']['name']}</h3>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 10px;">
                <tr style="border-bottom: 1px solid #334455;"><td style="color: #88aaff; padding: 2px;">NORAD ID</td><td style="text-align: right;">{asset['data']['catnr']}</td></tr>
                <tr style="border-bottom: 1px solid #334455;"><td style="color: #88aaff; padding: 2px;">INCLINATION</td><td style="text-align: right;">{inclination_deg:.2f}°</td></tr>
                <tr style="border-bottom: 1px solid #334455;"><td style="color: #88aaff; padding: 2px;">PERIOD</td><td style="text-align: right;">{period_min:.2f} min</td></tr>
                <tr style="border-bottom: 1px solid #334455;"><td style="color: #88aaff; padding: 2px;">ECCENTRICITY</td><td style="text-align: right;">{eccentricity:.4f}</td></tr>
            </table>
            <div style="background: rgba(0, 20, 40, 0.5); padding: 5px; border: 1px solid #334455; text-align: center;">
                STATUS: {status_html}
            </div>
        </div>
        """
        
        cartesian_active = []
        cartesian_ghost = []
        
        for t in times:
            seconds = (t - epoch) * 86400.0
            
            pos_orig = sat.at(t).position.km
            cartesian_ghost.extend([seconds, pos_orig[0]*1000, pos_orig[1]*1000, pos_orig[2]*1000])
            
            if maneuver and t.tt >= maneuver['time'].tt:
                dt_sec = (t - maneuver['time']) * 86400.0
                current_state = maneuver['orbit_new'].propagate(dt_sec * u.s)
                pos_safe = current_state.r.to(u.km).value
                cartesian_active.extend([seconds, pos_safe[0]*1000, pos_safe[1]*1000, pos_safe[2]*1000])
            else:
                cartesian_active.extend([seconds, pos_orig[0]*1000, pos_orig[1]*1000, pos_orig[2]*1000])

        # PART A: The BUS (Box Body)
        czml.append({
            "id": f"{asset['data']['id']}_active",
            "name": asset['data']['name'],
            "description": description,
            "availability": f"{times[0].utc_iso()}/{times[-1].utc_iso()}",
            "box": {
                # Gold Box Body
                "dimensions": {"cartesian": [30000.0, 30000.0, 50000.0]}, # Even larger size for visibility
                "material": {"solidColor": {"color": {"rgba": [255, 200, 0, 255]}}},
                "show": True
            },
            "label": {
                "text": asset['data']['name'],
                "font": "12pt Segoe UI",
                "fillColor": {"rgba": [200, 240, 255, 255]},
                "showBackground": True,
                "backgroundColor": {"rgba": [0, 20, 40, 180]},
                "pixelOffset": {"cartesian2": [30, -30]},
                "horizontalOrigin": "LEFT",
                "scaleByDistance": {"nearFarScalar": [1.5e2, 1.0, 8.0e6, 0.0]}
            },
            "path": {
                "show": True,
                "width": 1,
                "material": {"solidColor": {"color": {"rgba": [0, 255, 255, 100] if not maneuver else [0, 255, 100, 255]}}},
                "resolution": 120,
                "leadTime": 0,
                "trailTime": 100000 
            },
            "position": {
                "interpolationAlgorithm": "LAGRANGE",
                "interpolationDegree": 5,
                "referenceFrame": "FIXED",
                "epoch": times[0].utc_iso(),
                "cartesian": cartesian_active
            }
        })

        # PART B: The PANELS (Blue Wings attached to same position)
        czml.append({
            "id": f"{asset['data']['id']}_panels",
            "name": "Solar Arrays",
            "availability": f"{times[0].utc_iso()}/{times[-1].utc_iso()}",
            "box": {
                # Wide Blue Panels
                "dimensions": {"cartesian": [60000.0, 6000.0, 200.0]}, 
                "material": {"grid": {"color": {"rgba": [0, 100, 255, 255]}, "cellAlpha": 0.5, "lineCount": {"cartesian2": [8, 1]}}},
                "show": True
            },
            "position": {
                "reference": f"{asset['data']['id']}_active#position" # Lock to body
            }
        })
        
        if maneuver:
            czml.append({
                "id": f"{asset['data']['id']}_ghost",
                "name": f"{asset['data']['name']} (Predicted Impact)",
                "availability": f"{maneuver['time'].utc_iso()}/{times[-1].utc_iso()}",
                "path": {
                    "show": True,
                    "width": 1,
                    "material": {
                        "polylineDash": {
                            "color": {"rgba": [255, 50, 50, 128]},
                            "dashLength": 16.0
                        }
                    },
                    "resolution": 120
                },
                "position": {
                    "epoch": times[0].utc_iso(),
                    "cartesian": cartesian_ghost
                }
            })
            
            pos_burn = sat.at(maneuver['time']).position.km * 1000
            czml.append({
                "id": f"{asset['data']['id']}_burn",
                "name": "Auto-Maneuver Event",
                "position": {"cartesian": [pos_burn[0], pos_burn[1], pos_burn[2]]},
                "point": {
                    "pixelSize": 15,
                    "color": {"rgba": [255, 200, 0, 255]},
                    "outlineColor": {"rgba": [0,0,0,255]},
                    "outlineWidth": 2
                },
                "label": {
                    "text": "⚠ THRUSTERS",
                    "font": "bold 12pt Monospace",
                    "fillColor": {"rgba": [255, 200, 0, 255]},
                    "showBackground": True,
                    "pixelOffset": {"cartesian2": [0, 15]}
                }
            })

    # --- 4. ASTEROID GENERATION (99942 Apophis Proxy) ---
    print("  - Tracking Near-Earth Objects (Apophis)...")
    # Approximate Elements for visual simulation
    apophis_orbit = Orbit.from_classical(
        Earth,
        0.92 * u.AU,        # Semi-major axis
        0.19 * u.one,       # Eccentricity
        3.33 * u.deg,       # Inclination
        126.4 * u.deg,      # RAAN
        271.3 * u.deg,      # Arg of Periapsis
        203.0 * u.deg,      # True Anomaly
        epoch=Time(start_time.utc_datetime())
    )

    asteroid_cart = []
    for t in times:
        dt_sec = (t - epoch) * 86400.0
        state = apophis_orbit.propagate(dt_sec * u.s)
        pos = state.r.to(u.km).value
        asteroid_cart.extend([dt_sec, pos[0]*1000, pos[1]*1000, pos[2]*1000])

    czml.append({
        "id": "apophis_99942",
        "name": "99942 APOPHIS (PHA)",
        "description": "Potentially Hazardous Asteroid<br>Class: Aten",
        "availability": f"{times[0].utc_iso()}/{times[-1].utc_iso()}",
        "point": {
            "show": True,
            "pixelSize": 10,
            "color": {"rgba": [200, 100, 50, 255]}, # Brown/Orange
            "outlineColor": {"rgba": [255, 255, 255, 255]},
            "outlineWidth": 1
        },
        "label": {
            "text": "99942 APOPHIS",
            "font": "11pt monospace",
            "fillColor": {"rgba": [255, 150, 100, 255]},
            "showBackground": True,
            "backgroundColor": {"rgba": [20, 10, 0, 200]},
            "pixelOffset": {"cartesian2": [20, 20]}
        },
        "path": {
            "show": True,
            "width": 2,
            "material": {"solidColor": {"color": {"rgba": [255, 100, 255, 150]}}}, # Purple/Pink Orbit
            "leadTime": 0,
            "trailTime": 100000 # Long trail
        },
        "position": {
            "epoch": times[0].utc_iso(),
            "cartesian": asteroid_cart
        }
    })

    # 2. Render Real Debris (High Visibility)
    for deb in real_debris:
        is_threat = deb.model.satnum in threat_debris_ids
        
        color = [255, 30, 30, 255] if is_threat else [180, 200, 220, 150]
        scale = 10 if is_threat else 4
        
        czml.append({
            "id": f"deb_{deb.model.satnum}",
            "name": deb.name,
            "point": {
                "show": True,
                "pixelSize": scale,
                "color": {"rgba": color},
                "outlineColor": {"rgba": [0,0,0,255]},
                "outlineWidth": 1 if is_threat else 0
            },
            "position": {
                "epoch": times[0].utc_iso(),
                "cartesian": [] 
            }
        })
        
        deb_cart = []
        step_stride = 2 # Optimization: 5 -> 2 for smoother playback
        for t_idx in range(0, len(times), step_stride): # Step 5
            t = times[t_idx]
            pos = deb.at(t).position.km
            sec = (t - epoch) * 86400.0
            deb_cart.extend([sec, pos[0]*1000, pos[1]*1000, pos[2]*1000])
        czml[-1]["position"]["cartesian"] = deb_cart

    # 3. Background Static Debris (Density)
    for i in range(800):
        u_vec = np.random.normal(0, 1, 3)
        u_vec /= np.linalg.norm(u_vec)
        dist = 6371 + 400 + np.random.random() * 1000
        pos = u_vec * dist * 1000
        
        czml.append({
            "id": f"static_deb_{i}",
            "name": "Background Debris",
            "position": {"cartesian": [pos[0], pos[1], pos[2]]},
            "point": {
                "show": True,
                "pixelSize": 2,
                "color": {"rgba": [100, 100, 100, 80]}
            }
        })
        
    return czml

if __name__ == "__main__":
    # Standalone execution mode
    data = get_czml()
    with open('output.czml', 'w') as f:
        json.dump(data, f)
