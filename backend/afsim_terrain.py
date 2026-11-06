"""Compile declared LOS barriers into native checks at each fire cycle."""
from gentactix import terrain_process


def functions(world):
    cfg = terrain_process.configuration(world)
    if not cfg:return ''
    checks = []
    for r in cfg['barriers']:
        if 'direct_fire' not in r['blocks']:continue
        a,b=r['a'],r['b']
        checks.append(f' if (GtxTerrainCross(actor.Latitude(),actor.Longitude(),target.Latitude(),target.Longitude(),{a["lat"]},{a["lng"]},{b["lat"]},{b["lng"]})) {{ return true; }}')
    return '''script double GtxTerrainSide(double ax,double ay,double bx,double by,double cx,double cy)
 return (by-ay)*(cx-ax)-(bx-ax)*(cy-ay);
end_script
script bool GtxTerrainCross(double ax,double ay,double bx,double by,double cx,double cy,double dx,double dy)
 if (Math.Max(ax,bx)<Math.Min(cx,dx) || Math.Max(cx,dx)<Math.Min(ax,bx) || Math.Max(ay,by)<Math.Min(cy,dy) || Math.Max(cy,dy)<Math.Min(ay,by)) { return false; }
 return GtxTerrainSide(ax,ay,bx,by,cx,cy)*GtxTerrainSide(ax,ay,bx,by,dx,dy)<=0 && GtxTerrainSide(cx,cy,dx,dy,ax,ay)*GtxTerrainSide(cx,cy,dx,dy,bx,by)<=0;
end_script
script bool GtxTerrainBlocked(WsfPlatform actor,WsfPlatform target)
''' + '\n'.join(checks) + '\n return false;\nend_script\n'
