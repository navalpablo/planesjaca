#!/usr/bin/env python3
"""Real-data Pyrenees wall map. No image generation, no copied reference-site code."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib import patheffects
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.transforms import Bbox
import numpy as np
from PIL import Image
from pyproj import Transformer
import requests
from scipy.ndimage import gaussian_filter, map_coordinates
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union, linemerge

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"
PROJ = Transformer.from_crs(4326, 25831, always_xy=True)
INV = Transformer.from_crs(25831, 4326, always_xy=True)
TO_MERC = Transformer.from_crs(25831, 3857, always_xy=True)
PAPER = "#f3efe3"
INK = "#404937"
WATER = "#638e9e"
USER_AGENT = "PyreneesWallMap/1.0 (open cartography; Python requests)"
RADIUS = 6378137.0
WORLD_HALF = math.pi * RADIUS
FRAME = [.028, .104, .944, .733]
MAP_WIDTH_M = 470000.0
MAP_HEIGHT_M = MAP_WIDTH_M * (FRAME[3] * .6) / (FRAME[2] * 1.5)
CX, CY = PROJ.transform(.65, 42.81)
EXTENT = [CX-MAP_WIDTH_M/2, CX+MAP_WIDTH_M/2,
          CY-MAP_HEIGHT_M/2, CY+MAP_HEIGHT_M/2]
PEAK_NAMES = [
    "aneto", "posets", "monte perdido", "mont perdu", "vignemale",
    "balait", "balaït", "balaï", "pica d'estats", "pica d’estats",
    "pic du midi d'ossau", "pic du midi d’ossau", "ossau", "midi d'osau", "pico de midi",
    "pic du midi de bigorre", "pic d'anie", "pic d’anie", "auñamendi",
    "petit astazou", "taillon", "tallón", "la munia", "bachimaña",
    "gran facha", "grande fache", "garmo negro", "infiernos",
    "perdiguero", "bisaur", "batchimale", "grand quairat", "neouvielle",
    "néouvielle", "montcalm", "comapedrosa", "coma pedrosa",
    "puigmal", "canigou", "canigo", "carlit", "pédraforca", "pedraforca", "pollegó superior",
    "orhi", "ori", "larrun", "la rhune", "txindoki", "tuc de mulleres",
    "besiberri", "pica de cervi", "pico de cervi", "cotiella",
    "pico de alba", "pico russell", "pic de troumouse", "pic long"
]
TOWN_NAMES = [
    "jaca", "pamplona", "iruña", "huesca", "pau", "tarbes", "lourdes",
    "saint-gaudens", "bagnères-de-luchon", "luchon", "benasque", "benasc",
    "ainsa", "aínsa", "sabiñánigo", "sabinanigo", "biescas", "torla",
    "broto", "canfranc", "vielha", "viella", "sort", "tremp",
    "la seu d'urgell", "la seu d’urgell", "andorra la vella",
    "puigcerdà", "puigcerda", "ripoll", "foix", "prades", "céret",
    "ceret", "saint-jean-pied-de-port", "saint-lary", "aragnouet",
    "bagà", "baga", "isaba", "izaba", "roncal", "organyà",
    "organya", "saint-girons", "oloron", "arudy", "laruns"
]

def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c)).replace("’", "'")

def selected(name, names):
    n = normalized(name)
    return any(re.search(r"(?<![a-z0-9])" + re.escape(normalized(s)) + r"(?![a-z0-9])", n) for s in names)

def fetch_bytes(url, target):
    if target.exists():
        return target.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            target.write_bytes(r.content)
            return r.content
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable download state")

def dem_grid(dpi, zoom):
    # Raster matches the physical map panel, not the page margins.
    width = round(150 / 2.54 * dpi * FRAME[2])
    height = round(60 / 2.54 * dpi * FRAME[3])
    x0, x1, y0, y1 = EXTENT
    px = np.linspace(x0, x1, width, dtype=np.float64)
    py = np.linspace(y1, y0, height, dtype=np.float64)
    n = 2 ** zoom
    span = 2 * WORLD_HALF / n
    # Exact geographic footprint of the projected map, including edge curvature.
    edge_x = np.concatenate([px, px, np.full(height, x0), np.full(height, x1)])
    edge_y = np.concatenate([np.full(width, y0), np.full(width, y1), py, py])
    mx, my = TO_MERC.transform(edge_x, edge_y)
    tx0, tx1 = math.floor((min(mx)+WORLD_HALF)/span), math.floor((max(mx)+WORLD_HALF)/span)
    ty0, ty1 = math.floor((WORLD_HALF-max(my))/span), math.floor((WORLD_HALF-min(my))/span)
    tiles = [(x,y) for y in range(ty0,ty1+1) for x in range(tx0,tx1+1)]
    print(f"Downloading {len(tiles)} real elevation tiles at zoom {zoom}.", flush=True)
    mosaic = np.empty(((ty1-ty0+1)*256, (tx1-tx0+1)*256), dtype=np.float32)

    def tile(item):
        x,y = item
        data = fetch_bytes(
            f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{x}/{y}.png",
            CACHE / "terrain" / str(zoom) / str(x) / f"{y}.png")
        a = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
        return x,y,a[:,:,0]*256 + a[:,:,1] + a[:,:,2]/256 - 32768

    with ThreadPoolExecutor(max_workers=6) as pool:
        for k,(x,y,a) in enumerate(pool.map(tile,tiles),1):
            mosaic[(y-ty0)*256:(y-ty0+1)*256,(x-tx0)*256:(x-tx0+1)*256] = a
            if k % 100 == 0:
                print(f"Elevation tiles {k}/{len(tiles)}", flush=True)
    out = np.empty((height,width),dtype=np.float32)
    # Inverse-map each target pixel; no fictitious heights or edge padding.
    for row in range(0,height,128):
        xx,yy = np.meshgrid(px,py[row:row+128])
        mx,my = TO_MERC.transform(xx,yy)
        col = (mx+WORLD_HALF)/span*256 - tx0*256 - .5
        rr = (WORLD_HALF-my)/span*256 - ty0*256 - .5
        if col.min() < 0 or rr.min() < 0 or col.max() > mosaic.shape[1]-1 or rr.max() > mosaic.shape[0]-1:
            raise ValueError("DEM does not cover the print footprint.")
        out[row:row+len(xx)] = map_coordinates(mosaic,[rr,col],order=1,mode="nearest")
    if not np.isfinite(out).all() or out.max() < 3300:
        raise ValueError("Invalid Pyrenees elevation raster.")
    return out, (x1-x0)/(width-1), (y1-y0)/(height-1)

def relief_image(dem, dx, dy):
    softened = gaussian_filter(dem, .75)
    gy,gx = np.gradient(softened,dy,dx)
    # Image rows run southward; the illumination vectors use the same orientation.
    denom = np.sqrt(1 + gx*gx + gy*gy)
    shade = np.zeros_like(dem)
    for az,weight in [(315,.55),(270,.25),(45,.20)]:
        rad,alt = math.radians(az),math.radians(40)
        sunx,suny,sunz = math.sin(rad)*math.cos(alt),-math.cos(rad)*math.cos(alt),math.sin(alt)
        shade += weight*np.clip((-gx*sunx-gy*suny+sunz)/denom,0,1)
    heights = [0,700,1300,1900,2500,3100,3500]
    colors = np.array([[206,216,186],[196,207,177],[204,207,179],
                       [217,209,181],[225,215,194],[233,229,215],[243,240,229]])/255.
    rgb = np.stack([np.interp(dem,heights,colors[:,i]) for i in range(3)],axis=-1).astype("float32")
    rgb *= (.72 + .40*shade)[...,None]
    rgb[dem <= 0] = np.array([.73,.82,.82])
    return np.asarray(np.clip(rgb*255,0,255),dtype=np.uint8)

def osm_data():
    # A cached snapshot is included with the outputs for auditing and reproduction.
    path = CACHE / "osm.json"
    if path.exists():
        return json.loads(path.read_text())
    xs = [EXTENT[0],EXTENT[1],EXTENT[0],EXTENT[1]]
    ys = [EXTENT[2],EXTENT[2],EXTENT[3],EXTENT[3]]
    lon,lat = INV.transform(xs,ys)
    box = f"{min(lat)-.03},{min(lon)-.03},{max(lat)+.03},{max(lon)+.03}"
    query = f"""[out:json][timeout:180][maxsize:536870912];
(
 way["waterway"="river"]({box});
 way["natural"="water"]({box});
 relation["natural"="water"]["type"="multipolygon"]({box});
 way["highway"~"^(motorway|trunk|primary)$"]({box});
 node["place"~"^(city|town|village)$"]({box});
 node["natural"="peak"]["name"]({box});
);
out geom;"""
    failures = []
    for endpoint in ["https://overpass-api.de/api/interpreter",
                     "https://overpass.kumi.systems/api/interpreter",
                     "https://overpass.private.coffee/api/interpreter"]:
        try:
            r = requests.post(endpoint,data={"data":query},
                              headers={"User-Agent":USER_AGENT},timeout=240)
            r.raise_for_status()
            data = r.json()
            if data.get("remark") or not data.get("elements"):
                raise ValueError(data.get("remark","Empty OSM response"))
            CACHE.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(data,ensure_ascii=False))
            return data
        except (requests.RequestException,ValueError) as e:
            failures.append(f"{endpoint}: {e}")
    raise RuntimeError("Unable to obtain complete cartographic data: " + "; ".join(failures))

def projected(geom):
    if len(geom) < 2:
        return None
    x,y = PROJ.transform([p["lon"] for p in geom],[p["lat"] for p in geom])
    return np.column_stack([x,y])

def altitude(tags):
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(tags.get("ele","")))
    return float(match[0].replace(",",".")) if match else None

def name_of(tags):
    return tags.get("name:es") or tags.get("name") or tags.get("name:ca") or ""

def water_polygons(element):
    if element["type"] == "way":
        points = projected(element.get("geometry",[]))
        if points is not None and np.allclose(points[0],points[-1]):
            p = Polygon(points)
            if p.is_valid:
                return [p]
        return []
    outers,inners = [],[]
    for m in element.get("members",[]):
        p = projected(m.get("geometry",[]))
        if p is not None:
            (inners if m.get("role")=="inner" else outers).append(LineString(p))
    if not outers:
        return []
    shell = unary_union(list(polygonize(unary_union(outers))))
    holes = unary_union(list(polygonize(unary_union(inners)))) if inners else None
    shape = shell.difference(holes) if holes is not None else shell
    return list(shape.geoms) if shape.geom_type=="MultiPolygon" else ([shape] if shape.geom_type=="Polygon" else [])

def build(args):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    data = osm_data()
    dem,dx,dy = dem_grid(args.dpi,args.zoom)
    rgb = relief_image(dem,dx,dy)
    plt.rcParams.update({"font.family":"DejaVu Serif","pdf.fonttype":42,
                         "svg.fonttype":"none","axes.linewidth":.65})
    fig = plt.figure(figsize=(150/2.54,60/2.54),facecolor=PAPER,dpi=args.dpi)
    ax = fig.add_axes(FRAME,facecolor=PAPER)
    ax.set_xlim(EXTENT[:2]);ax.set_ylim(EXTENT[2:])
    ax.imshow(rgb,extent=EXTENT,origin="upper",interpolation="bilinear",zorder=0)
    ax.set_aspect("equal")
    ax.set_xticks([]);ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor("#81846c")
    # A restrained contour layer, sampled from the same real elevation raster.
    h,w = dem.shape
    step = max(1,round(w/2600))
    ax.contour(np.linspace(EXTENT[0],EXTENT[1],w)[::step],
               np.linspace(EXTENT[3],EXTENT[2],h)[::step],dem[::step,::step],
               levels=np.arange(500,3501,500),colors="#71634f",
               linewidths=.18,alpha=.17,zorder=1)
    roads,rivers,river_labels,peaks,towns = [],[],{},[],[]
    all_peak_points=[]
    water_count=0
    for e in data["elements"]:
        tags=e.get("tags",{})
        geom=e.get("geometry",[])
        p=projected(geom) if geom else None
        if tags.get("highway") and p is not None:
            roads.append(p)
        elif tags.get("waterway")=="river" and p is not None:
            rivers.append(p)
            nm=name_of(tags)
            if nm:
                river_labels.setdefault(normalized(nm),{"name":nm,"segments":[]})["segments"].append(LineString(p))
        elif tags.get("natural")=="water":
            for poly in water_polygons(e):
                if poly.area<16000:
                    continue
                # Oppositely oriented inner rings leave the real island relief visible.
                poly=orient(poly,sign=1.0)
                paths=[]
                for ring in [poly.exterior,*poly.interiors]:
                    vertices=np.asarray(ring.coords)
                    codes=np.full(len(vertices),MplPath.LINETO,dtype=np.uint8)
                    codes[0]=MplPath.MOVETO;codes[-1]=MplPath.CLOSEPOLY
                    paths.append(MplPath(vertices,codes))
                ax.add_patch(PathPatch(MplPath.make_compound_path(*paths),
                             facecolor="#8cabb0",edgecolor=WATER,linewidth=.18,zorder=3))
                water_count+=1
        elif e["type"]=="node" and tags.get("natural")=="peak":
            nm=name_of(tags)
            alt=altitude(tags)
            if alt and alt>800:
                x,y=PROJ.transform(e["lon"],e["lat"])
                all_peak_points.append((nm,alt,x,y))
                if selected(nm,PEAK_NAMES):
                    peaks.append((nm,alt,x,y))
        elif e["type"]=="node" and tags.get("place"):
            nm=name_of(tags)
            x,y=PROJ.transform(e["lon"],e["lat"])
            towns.append((nm,x,y))
    # Important massifs sometimes use a different primary name in OSM.
    for nm,lon,lat in [("Midi d'Ossau",-.4387,42.8433),
                       ("Perdiguero",.5192,42.6925),
                       ("Néouvielle",.1159,42.8369),
                       ("Taillón",-.0526,42.6931)]:
        xx,yy=PROJ.transform(lon,lat)
        nearby=[p for p in all_peak_points if math.hypot(p[2]-xx,p[3]-yy)<600 and p[1]>2700]
        if nearby:
            p=min(nearby,key=lambda p:math.hypot(p[2]-xx,p[3]-yy))
            peaks=[q for q in peaks if math.hypot(q[2]-p[2],q[3]-p[3])>600]
            peaks.append((nm,p[1],p[2],p[3]))
    # Resolve editorial town choices to actual OSM points, avoiding same-name villages.
    chosen_towns=[]
    for target in json.loads((ROOT/"towns.json").read_text()):
        xx,yy=PROJ.transform(target["lon"],target["lat"])
        candidates=[q for q in towns if math.hypot(q[1]-xx,q[2]-yy)<2500]
        if candidates:
            nearest=min(candidates,key=lambda q:math.hypot(q[1]-xx,q[2]-yy))
            chosen_towns.append((target["name"],nearest[1],nearest[2]))
    towns=chosen_towns
    ax.add_collection(LineCollection(roads,colors="#9b8c70",linewidths=.22,alpha=.36,zorder=2))
    ax.add_collection(LineCollection(rivers,colors=WATER,linewidths=.38,alpha=.9,zorder=3))
    fig.text(.5,.921,"P I R I N E O S",ha="center",va="center",fontsize=82,color=INK)
    fig.text(.5,.872,"Cumbres, valles y aguas · Del Atlántico al Mediterráneo",
             ha="center",va="center",fontsize=24,fontstyle="italic",color="#74765f")
    # Reserve symbols first, then place labels with measured print-space bounds.
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    obstacles=[]
    placed=[]
    def inside(x,y):
        return EXTENT[0]+1500<x<EXTENT[1]-1500 and EXTENT[2]+1500<y<EXTENT[3]-1500
    def label(text,x,y,size,color,italic=False,offsets=None,rotation=0):
        if not inside(x,y):
            return False
        for ox,oy in offsets or [(0,0)]:
            a=ax.annotate(text,(x,y),xytext=(ox,oy),textcoords="offset points",
                          fontsize=size,color=color,ha="center",va="center",
                          fontstyle="italic" if italic else "normal",rotation=rotation,
                          zorder=7,clip_on=True,
                          path_effects=[patheffects.withStroke(linewidth=2.4,foreground=PAPER,alpha=.82)])
            b=a.get_window_extent(renderer).expanded(1.10,1.3)
            frame_box=ax.get_window_extent(renderer)
            if not frame_box.contains(b.x0,b.y0) or not frame_box.contains(b.x1,b.y1) or any(b.overlaps(q) for q in obstacles):
                a.remove()
                continue
            obstacles.append(b)
            placed.append({"label":text,"x":x,"y":y})
            return True
        return False
    seen=set()
    for nm,alt,x,y in sorted(peaks,key=lambda p:-p[1]):
        key=(round(x/1500),round(y/1500))
        if key in seen or not inside(x,y):
            continue
        seen.add(key)
        ax.plot(x,y,"^",markersize=6,markeredgewidth=.45,markeredgecolor=PAPER,color="#745f48",zorder=5)
        size=22 if alt>3200 else 19
        label(f"{nm}\n{round(alt):,} m".replace(","," "),x,y,size,"#504a3b",
              offsets=[(0,29),(0,-30),(70,0),(-70,0),(70,27),(-70,27)])
    # Valley names have priority over secondary town and river labels.
    for v in json.loads((ROOT/"valleys.json").read_text()):
        x,y=PROJ.transform(v["lon"],v["lat"])
        label(v["name"],x,y,18,"#777c63",True,
              offsets=[(0,0),(0,19),(0,-19),(35,0),(-35,0)])
    for nm,x,y in sorted(towns,key=lambda p:0 if normalized(p[0])=="jaca" else 1):
        if not inside(x,y):
            continue
        jaca=normalized(nm)=="jaca"
        ax.plot(x,y,"o",markersize=5.5 if jaca else 3.5,
                markeredgecolor=PAPER,markeredgewidth=.8,color=INK,zorder=5)
        label("JACA" if jaca else nm,x,y,24 if jaca else 19,INK,
              offsets=[(0,-19),(0,19),(55,0),(-55,0),(0,-38),(0,38),(75,25),(-75,25)])
    # Connected OSM segments are merged before selecting a label anchor.
    merged_rivers=[]
    for entry in river_labels.values():
        shape=unary_union(entry["segments"]).intersection(box(EXTENT[0],EXTENT[2],EXTENT[1],EXTENT[3]))
        if shape.is_empty or shape.geom_type not in ("LineString","MultiLineString"):
            continue
        if shape.geom_type=="MultiLineString":
            shape=linemerge(shape)
        lines=list(shape.geoms) if shape.geom_type=="MultiLineString" else [shape]
        line=max(lines,key=lambda q:q.length)
        if shape.length>22000:
            anchor=line.interpolate(.5,normalized=True)
            merged_rivers.append((entry["name"],shape.length,anchor.x,anchor.y))
    main_rivers=["aragon","gállego","cinca","esera","garona","garonne",
                 "noguera ribagorcana","noguera pallaresa","gave de pau","gave d'aspe","aude","tet"]
    for nm,length,x,y in sorted(merged_rivers,key=lambda q:(not selected(q[0],main_rivers),-q[1])):
        label(nm,x,y,16,"#4d7889",True,
              offsets=[(0,9),(0,-9),(0,0),(15,15),(-15,-15)])
    # Scale in projected metres. UTM zone 31 gives low scale distortion here.
    fig.text(.03,.065,"N ↑",fontsize=21,color=INK)
    bar=fig.add_axes([.074,.052,.10,.03]);bar.set_xlim(0,MAP_WIDTH_M*.10/FRAME[2])
    bar.set_ylim(0,1);bar.axis("off")
    for i in range(5):
        bar.plot([i*10000,(i+1)*10000],[.7,.7],color=INK if i%2==0 else "#9c9e87",linewidth=4)
    for km in (0,25,50):
        bar.text(km*1000,.18,str(km),ha="center",fontsize=13,color=INK)
    bar.text(55000,.18,"km",fontsize=13,color=INK)
    fig.text(.97,.063,"Relieve real · Terrain Tiles / Mapzen (SRTM y otras fuentes)    |    © OpenStreetMap contributors",
             ha="right",fontsize=14,color="#666e5a")
    fig.text(.97,.035,"150 × 60 cm · ETRS89 / UTM 31N · Cartografía decorativa",
             ha="right",fontsize=13,color="#666e5a")
    stem=OUTPUT/"pirineos-150x60cm"
    fig.savefig(str(stem)+".pdf",dpi=args.dpi,facecolor=PAPER)
    fig.savefig(str(stem)+".png",dpi=args.dpi,facecolor=PAPER)
    fig.savefig(OUTPUT/"vista-previa.jpg",dpi=50,facecolor=PAPER,pil_kwargs={"quality":92})
    plt.close(fig)
    with Image.open(str(stem)+".png") as png:
        pixel_size=list(png.size)
        embedded_dpi=list(png.info.get("dpi",[]))
    assert abs(pixel_size[0]-150/2.54*args.dpi)<2
    assert abs(pixel_size[1]-60/2.54*args.dpi)<2
    assert embedded_dpi and abs(embedded_dpi[0]-args.dpi)<.1
    pdf_bytes=Path(str(stem)+".pdf").read_bytes()
    media=re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)",pdf_bytes)
    assert media, "PDF page dimensions are missing."
    pdf_mm=[float(media[1])/72*25.4,float(media[2])/72*25.4]
    assert abs(pdf_mm[0]-1500)<.01 and abs(pdf_mm[1]-600)<.01
    manifest={"created_utc":datetime.now(timezone.utc).isoformat(),
              "size_cm":[150,60],"dpi":args.dpi,"epsg":25831,
              "png_pixels":pixel_size,"png_dpi":embedded_dpi,"pdf_page_mm":pdf_mm,
              "extent_m":EXTENT,"terrain_zoom":args.zoom,
              "terrain_url":"https://registry.opendata.aws/terrain-tiles/",
              "osm_timestamp":data.get("osm3s",{}).get("timestamp_osm_base"),
              "osm_elements":len(data["elements"]),"water_polygons":water_count,
              "elevation_m":[float(dem.min()),float(dem.max())],
              "placed_labels":placed,"files":{}}
    for file in OUTPUT.glob("*"):
        if file.suffix in (".pdf",".png",".jpg"):
            manifest["files"][file.name]={"bytes":file.stat().st_size,
                                        "sha256":hashlib.sha256(file.read_bytes()).hexdigest()}
    (OUTPUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (OUTPUT/"osm-snapshot.json").write_text(json.dumps(data,ensure_ascii=False))
    print(json.dumps({k:v for k,v in manifest.items() if k!="placed_labels"},indent=2),flush=True)
    assert any(p["label"]=="JACA" for p in placed), "Jaca must appear on the print."
    assert any("aneto" in normalized(p["label"]) for p in placed), "Aneto must appear."
    assert len(rivers)>20 and len(placed)>25, "Cartographic layers are incomplete."
    assert water_count>20, "The lake layer is incomplete."

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi",type=int,choices=[100,150,200,300],default=200)
    parser.add_argument("--zoom",type=int,choices=[10,11,12],default=12)
    build(parser.parse_args())
