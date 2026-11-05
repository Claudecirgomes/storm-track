"""Render a real local scene over the same NASA terrain used by the map."""
import io
import json
import math
from pathlib import Path
from urllib.request import urlopen

from PIL import Image, ImageDraw
from backend.app.adapters import regional_satellite as regional


def main():
    workspace=Path(__file__).resolve().parents[3]
    frame=regional.catalog()['frames'][-1]
    west,south,east,north=frame['bounds'];zoom=5;size=256*2**zoom
    def pixel(lon,lat):
        return ((lon+180)/360*size,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*size)
    left,top=pixel(west,north);right,bottom=pixel(east,south)
    x0,x1=int(left//256),int(right//256);y0,y1=int(top//256),int(bottom//256)
    mosaic=Image.new('RGB',((x1-x0+1)*256,(y1-y0+1)*256))
    cache=workspace/'output'/'terrain-cache';cache.mkdir(exist_ok=True)
    for x in range(x0,x1+1):
        for y in range(y0,y1+1):
            file=cache/f'{zoom}-{x}-{y}.jpg'
            if not file.exists():
                url=f'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{zoom}/{y}/{x}.jpg'
                with urlopen(url,timeout=15) as response:
                    data=response.read(2*1024**2+1)
                if len(data)>2*1024**2:
                    raise ValueError('Terrain tile exceeds limit')
                Image.open(io.BytesIO(data)).verify();file.write_bytes(data)
            with Image.open(file) as tile:
                mosaic.paste(tile,(256*(x-x0),256*(y-y0)))
    with Image.open(regional.root()/frame['images']['reference']) as clouds:
        width,height=clouds.size
        base=mosaic.crop((round(left-x0*256),round(top-y0*256),round(right-x0*256),round(bottom-y0*256))).resize((width,height),Image.Resampling.BILINEAR).convert('RGBA')
        base=Image.alpha_composite(base,clouds.convert('RGBA'))
    raw=(workspace/'frontend/assets/map-base.js').read_text(encoding='utf-8')
    geometry=json.loads(raw[raw.index('{'):raw.rindex('}')+1])
    draw=ImageDraw.Draw(base)
    for collection in ('countries','states'):
        for feature in geometry[collection]['features']:
            shape=feature['geometry'];polygons=[shape['coordinates']] if shape['type']=='Polygon' else shape['coordinates']
            for polygon in polygons:
                for ring in polygon:
                    points=[((pixel(lon,lat)[0]-left)/(right-left)*width,(pixel(lon,lat)[1]-top)/(bottom-top)*height) for lon,lat,*_ in ring]
                    if len(points)>1:
                        draw.line(points,fill=(226,230,220,230),width=1)
    # Same regional framing as the map's reference shortcut, within the wider archive.
    _,view_top=pixel(west,-18);_,view_bottom=pixel(west,-36)
    base=base.crop((0,round((view_top-top)/(bottom-top)*height),width,round((view_bottom-top)/(bottom-top)*height)))
    width,height=base.size;draw=ImageDraw.Draw(base)
    draw.rectangle((0,height-22,width,height),fill=(0,0,0,190))
    draw.text((8,height-17),f"NOAA GOES-19 {frame['end']} | NASA Blue Marble: terreno estatico 2004",fill='white')
    destination=workspace/'output/monitor-reference-real.png';base.convert('RGB').save(destination)
    print(json.dumps({'preview':str(destination),'scene':frame['id'],'end':frame['end'],'bounds':frame['bounds']}))


if __name__=='__main__':
    main()
