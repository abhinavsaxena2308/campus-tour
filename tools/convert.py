"""
Phase 1 converter: campus DXF files -> game assets (glTF + JSON).

Run from the project root with the venv active:
    python tools/convert.py

Reads : tools/input/campus_map.dxf   (3D: terrain, buildings, roads, trees)
        tools/input/campus_2d.dxf    (2D: footprints, height labels)
Writes: public/data/*.glb, *.json    (game assets)
        tools/output/preview.png     (top-down check image)

Coordinate convention in the exported files (three.js, Y up, meters):
    game.x =   cad.x - ORIGIN_X
    game.y =   cad.z - ORIGIN_Z      (height above the lowest terrain point)
    game.z = -(cad.y - ORIGIN_Y)
This is a pure rotation (no mirroring), so triangle winding is preserved.
The origin values are saved in meta.json so you can convert back to CAD.
"""
import argparse
import json
import re
from pathlib import Path

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
import trimesh
from matplotlib.collections import PolyCollection
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent

L_TERRAIN = "TPX_TERRAIN_TERRAIN_MESH"
L_BUILDINGS = "TPX_BUILDINGS"
L_BLD_HEIGHT = "TPX_BUILDING_HEIGHTS_TEXT"
L_ROAD_AXES = "TPX_ROADS_AXES"
L_ROAD_SURF = "TPX_ROADS_HATCH"
L_GREEN = "TPX_VEGETATION_GREEN_SPACES"
L_GREEN_SURF = "TPX_VEGETATION_GREEN_SPACES_HATCH"
L_WATER = "TPX_WATERWAYS"
L_WATER_SURF = "TPX_WATERWAYS_HATCH"
L_RAIL = "TPX_RAILWAYS_AXES"
L_TREES = "TPX_VEGETATION_TREES_INDIVIDUAL"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def entities(msp, layer, kind=None):
    return [e for e in msp
            if e.dxf.layer == layer and (kind is None or e.dxftype() == kind)]


def mesh_arrays(e):
    """ezdxf MESH -> (vertices Nx3, triangle faces Mx3). Fan-triangulates if needed."""
    V = np.array([tuple(v) for v in e.vertices], dtype=float)
    F = []
    for f in e.faces:
        for i in range(1, len(f) - 1):
            F.append((f[0], f[i], f[i + 1]))
    return V, np.array(F, dtype=np.int64)


def merge(parts):
    Vs, Fs, off = [], [], 0
    for V, F in parts:
        Vs.append(V)
        Fs.append(F + off)
        off += len(V)
    return np.vstack(Vs), np.vstack(Fs)


def face_up(V, F):
    """Flip winding so ground-like meshes face +Y (game space)."""
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    return F if n[:, 1].sum() >= 0 else F[:, ::-1]


def outward(V, F):
    """Flip winding of a closed solid so normals point outward (positive volume)."""
    P = V - V.mean(axis=0)
    vol = np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6.0
    return F if vol >= 0 else F[:, ::-1]


def write_glb(path, V, F, flat=False):
    m = trimesh.Trimesh(np.asarray(V, np.float32), np.asarray(F), process=False)
    if flat:
        m.unmerge_vertices()  # one vertex per face corner -> crisp flat shading
    _ = m.vertex_normals
    m.export(str(path), file_type="glb", include_normals=True)


def polyline_pts(e):
    if e.dxftype() == "POLYLINE":
        return np.array([tuple(v.dxf.location) for v in e.vertices], dtype=float)
    return np.array([(p[0], p[1], 0.0) for p in e.get_points("xy")], dtype=float)


def r2(a):
    return np.round(np.asarray(a, dtype=float), 2)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=ROOT / "tools" / "input", type=Path)
    ap.add_argument("--out", default=ROOT / "public" / "data", type=Path)
    ap.add_argument("--preview", default=ROOT / "tools" / "output" / "preview.png", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    args.preview.parent.mkdir(parents=True, exist_ok=True)

    print("Reading DXF files (binary, a few seconds)...")
    d3 = ezdxf.readfile(args.input / "campus_map.dxf")
    d2 = ezdxf.readfile(args.input / "campus_2d.dxf")
    m3, m2 = d3.modelspace(), d2.modelspace()

    # ---- terrain + origin ------------------------------------------------
    terr = entities(m3, L_TERRAIN, "MESH")[0]
    TV, TF = mesh_arrays(terr)
    CX = float((TV[:, 0].min() + TV[:, 0].max()) / 2)
    CY = float((TV[:, 1].min() + TV[:, 1].max()) / 2)
    ZB = float(TV[:, 2].min())

    def to_game(P):
        P = np.asarray(P, dtype=float)
        out = np.empty_like(P)
        out[..., 0] = P[..., 0] - CX
        out[..., 1] = P[..., 2] - ZB
        out[..., 2] = -(P[..., 1] - CY)
        return out

    def xy_to_game(P):  # 2D (x, y) CAD -> (x, z) game
        P = np.asarray(P, dtype=float)
        return np.column_stack([P[:, 0] - CX, -(P[:, 1] - CY)])

    # exact ground height from the terrain triangles (CAD coords)
    tri = mtri.Triangulation(TV[:, 0], TV[:, 1], TF)
    interp = mtri.LinearTriInterpolator(tri, TV[:, 2])

    def ground_cad(x, y):
        x, y = np.atleast_1d(x).astype(float), np.atleast_1d(y).astype(float)
        z = np.ma.filled(interp(x, y), np.nan)
        bad = np.isnan(z)
        if bad.any():  # outside the mesh: use nearest terrain vertex
            d = (TV[None, :, 0] - x[bad, None]) ** 2 + (TV[None, :, 1] - y[bad, None]) ** 2
            z[bad] = TV[d.argmin(axis=1), 2]
        return z

    TVg = to_game(TV)
    write_glb(args.out / "terrain.glb", TVg, face_up(TVg, TF))
    print(f"terrain.glb   {len(TV)} verts, {len(TF)} tris")

    # ---- buildings -------------------------------------------------------
    b3 = entities(m3, L_BUILDINGS, "MESH")
    parts = []
    spans, cents3 = [], []
    for e in b3:
        V, F = mesh_arrays(e)
        spans.append(float(np.ptp(V[:, 2])))
        cents3.append(V[:, :2].mean(axis=0))
        Vg = to_game(V)
        parts.append((Vg, outward(Vg, F)))
    bV, bF = merge(parts)
    write_glb(args.out / "buildings.glb", bV, bF, flat=True)
    print(f"buildings.glb {len(b3)} buildings, {len(bF)} tris")
    spans, cents3 = np.array(spans), np.array(cents3)

    fp = entities(m2, L_BUILDINGS, "LWPOLYLINE")
    polys = [Polygon([(p[0], p[1]) for p in e.get_points("xy")]).buffer(0) for e in fp]
    tree = STRtree(polys)
    height = [None] * len(polys)
    for e in entities(m2, L_BLD_HEIGHT, "TEXT"):
        h = float(re.search(r"[\d.]+", e.dxf.text).group())
        pt = Point(e.dxf.insert.x, e.dxf.insert.y)
        hits = [int(i) for i in tree.query(pt, predicate="within")]
        hits.sort(key=lambda i: polys[i].area)
        j = next((i for i in hits if height[i] is None), None)
        if j is None:
            n = int(tree.nearest(pt))
            if polys[n].distance(pt) < 15 and height[n] is None:
                j = n
        if j is not None:
            height[j] = h
    from_text = sum(h is not None for h in height)

    # cross-check with the 3D meshes (z-span) and fill the gaps
    agree = checked = 0
    filled3d = default = 0
    for i, p in enumerate(polys):
        c = np.array(p.centroid.coords[0])
        d = np.hypot(*(cents3 - c).T)
        k = int(d.argmin())
        near = d[k] < 3.0
        if height[i] is not None and near:
            checked += 1
            agree += abs(spans[k] - height[i]) < 0.5
        elif height[i] is None:
            if near:
                height[i] = float(round(spans[k], 1))
                filled3d += 1
            else:
                height[i] = 6.0
                default += 1

    buildings = []
    for i, p in enumerate(polys):
        ring = np.array(p.exterior.coords)[:-1]
        gz = ground_cad(ring[:, 0], ring[:, 1])
        c = p.centroid
        gc = to_game(np.array([c.x, c.y, float(ground_cad(c.x, c.y)[0])]))
        base = float(gz.min() - ZB)
        buildings.append({
            "id": i,
            "name": "",
            "footprint": r2(xy_to_game(ring)).flatten().tolist(),   # [x, z, x, z, ...]
            "height": height[i],
            "base": round(base, 2),
            "top": round(base + height[i], 2),
            "center": [round(float(gc[0]), 2), round(float(gc[2]), 2)],
            "area": round(p.area, 1),
        })
    (args.out / "buildings.json").write_text(json.dumps(buildings, separators=(",", ":")))
    print(f"buildings.json {len(buildings)} footprints "
          f"(height: {from_text} from labels, {filled3d} from 3D, {default} default)")
    print(f"   label vs 3D height agree: {agree}/{checked}")

    # ---- roads -----------------------------------------------------------
    surf = entities(m3, L_ROAD_SURF, "MESH")
    rparts, rarea, rbox = [], [], []
    for e in surf:
        V, F = mesh_arrays(e)
        a, b = V[F[:, 1], :2] - V[F[:, 0], :2], V[F[:, 2], :2] - V[F[:, 0], :2]
        cr = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        rarea.append(float(np.abs(cr).sum() / 2))
        rbox.append((V[:, 0].min(), V[:, 1].min(), V[:, 0].max(), V[:, 1].max()))
        Vg = to_game(V)
        rparts.append((Vg, face_up(Vg, F)))
    rV, rF = merge(rparts)
    write_glb(args.out / "roads.glb", rV, rF)
    print(f"roads.glb     {len(surf)} surfaces, {len(rF)} tris")

    axes = entities(m3, L_ROAD_AXES, "POLYLINE")
    roads, ok = [], 0
    for i, e in enumerate(axes):
        P = polyline_pts(e)
        length = float(np.hypot(*np.diff(P[:, :2], axis=0).T).sum())
        width = None
        if i < len(surf):  # surfaces and axes share ordering; verify before trusting
            mid = P[len(P) // 2]
            b = rbox[i]
            if b[0] - 3 <= mid[0] <= b[2] + 3 and b[1] - 3 <= mid[1] <= b[3] + 3 and length > 1:
                width = round(rarea[i] / length, 1)
                ok += 1
        roads.append({"id": i, "length": round(length, 1), "width": width,
                      "points": r2(to_game(P)).flatten().tolist()})   # [x, y, z, ...]
    (args.out / "roads.json").write_text(json.dumps(roads, separators=(",", ":")))
    print(f"roads.json    {len(roads)} centerlines, {sum(r['length'] for r in roads) / 1000:.1f} km, "
          f"width matched for {ok}")

    # ---- greens, water, railway -----------------------------------------
    for layer, name in ((L_GREEN_SURF, "greens"), (L_WATER_SURF, "water")):
        ms = entities(m3, layer, "MESH")
        pp = []
        for e in ms:
            V, F = mesh_arrays(e)
            Vg = to_game(V)
            pp.append((Vg, face_up(Vg, F)))
        gV, gF = merge(pp)
        write_glb(args.out / f"{name}.glb", gV, gF)
        print(f"{name}.glb".ljust(14), f"{len(ms)} surfaces, {len(gF)} tris")

    def closed_polys(layer):
        return [r2(xy_to_game([(p[0], p[1]) for p in e.get_points("xy")])).flatten().tolist()
                for e in entities(m2, layer, "LWPOLYLINE")]

    features = {
        "greens": closed_polys(L_GREEN),
        "water": closed_polys(L_WATER),
        "rail": [r2(to_game(polyline_pts(e))).flatten().tolist()
                 for e in entities(m3, L_RAIL, "POLYLINE")],
    }
    (args.out / "features.json").write_text(json.dumps(features, separators=(",", ":")))
    print(f"features.json {len(features['greens'])} greens, {len(features['water'])} water, "
          f"{len(features['rail'])} rail")

    # ---- trees -----------------------------------------------------------
    ins = entities(m3, L_TREES, "INSERT")
    names = sorted({e.dxf.name for e in ins})
    tid = {n: i for i, n in enumerate(names)}
    protos, types, maxdev = {}, [], 0.0
    for n in names:
        ms = sorted([x for x in d3.blocks[n] if x.dxftype() == "MESH"],
                    key=lambda x: len(x.vertices))
        rec = {}
        for key, m in (("trunk", ms[0]), ("canopy", ms[-1])):
            V, F = mesh_arrays(m)
            r = float(np.abs(V[:, :2]).max())
            z0 = float(V[:, 2].min())
            h = float(np.ptp(V[:, 2]))
            U = np.column_stack([V[:, 0] / r, V[:, 1] / r, (V[:, 2] - z0) / h])
            if key not in protos:
                protos[key] = (U, F)
            else:
                maxdev = max(maxdev, float(np.abs(U - protos[key][0]).max()))
            rec[key] = {"r": round(r, 3), "z0": round(z0, 3), "h": round(h, 3)}
        types.append(rec)

    scene = trimesh.Scene()
    for key in ("trunk", "canopy"):
        U, F = protos[key]
        Ug = np.column_stack([U[:, 0], U[:, 2], -U[:, 1]])  # same axis swap, no translation
        m = trimesh.Trimesh(Ug.astype(np.float32), face_up(Ug, F), process=False)
        _ = m.vertex_normals
        scene.add_geometry(m, node_name=key, geom_name=key)
    scene.export(str(args.out / "trees.glb"), file_type="glb", include_normals=True)

    P = to_game(np.array([tuple(e.dxf.insert) for e in ins]))
    odd = sum(1 for e in ins if abs(e.dxf.rotation) > 1e-6 or
              abs(e.dxf.xscale - 1) > 1e-6 or abs(e.dxf.zscale - 1) > 1e-6)
    trees = {"types": types, "type": [tid[e.dxf.name] for e in ins],
             "positions": r2(P).flatten().tolist()}   # [x, y, z, ...] parallel to "type"
    (args.out / "trees.json").write_text(json.dumps(trees, separators=(",", ":")))
    print(f"trees.json    {len(ins)} trees, {len(types)} types "
          f"(shape deviation {maxdev:.4f}, rotated/scaled inserts: {odd})")

    # ---- meta ------------------------------------------------------------
    meta = {
        "units": "meters",
        "axis": "game.x = cad.x - originX; game.y = cad.z - originZ; game.z = -(cad.y - originY)",
        "originX": CX, "originY": CY, "originZ": ZB,
        "terrain": {"minX": float(TVg[:, 0].min()), "maxX": float(TVg[:, 0].max()),
                    "minZ": float(TVg[:, 2].min()), "maxZ": float(TVg[:, 2].max()),
                    "maxY": float(TVg[:, 1].max())},
        "counts": {"buildingMeshes": len(b3), "buildingFootprints": len(polys),
                   "roadSurfaces": len(surf), "roadCenterlines": len(axes),
                   "trees": len(ins), "treeTypes": len(types)},
    }
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2))

    # ---- preview ---------------------------------------------------------
    fig, ax = plt.subplots(figsize=(11, 11), dpi=110)
    ax.set_facecolor("#1b1f24")
    ax.tricontourf(TVg[:, 0], TVg[:, 2], TF, TVg[:, 1], levels=12, cmap="Greys_r", alpha=0.35)
    ax.add_collection(PolyCollection(
        [np.array(g).reshape(-1, 2) for g in features["greens"]],
        facecolors="#2f6b34", edgecolors="none", alpha=0.7))
    ax.add_collection(PolyCollection(
        [np.array(g).reshape(-1, 2) for g in features["water"]],
        facecolors="#3b8fd0", edgecolors="none"))
    ax.add_collection(PolyCollection(
        [rV[t][:, [0, 2]] for t in rF], facecolors="#9aa4ad", edgecolors="none"))
    for r in features["rail"]:
        q = np.array(r).reshape(-1, 3)
        ax.plot(q[:, 0], q[:, 2], color="#d98c3f", lw=1.2)
    tp = np.array(trees["positions"]).reshape(-1, 3)
    ax.scatter(tp[:, 0], tp[:, 2], s=1.0, c="#3cb371", alpha=0.45, linewidths=0)
    bh = np.array([b["height"] for b in buildings])
    pc = PolyCollection([np.array(b["footprint"]).reshape(-1, 2) for b in buildings],
                        array=bh, cmap="YlOrBr", edgecolors="#222", linewidths=0.2)
    pc.set_clim(3, 18)
    ax.add_collection(pc)
    ax.set_xlim(meta["terrain"]["minX"] - 20, meta["terrain"]["maxX"] + 20)
    ax.set_ylim(meta["terrain"]["maxZ"] + 20, meta["terrain"]["minZ"] - 20)  # +z is south -> north-up
    ax.set_aspect("equal")
    ax.set_title("campus preview, north up (game x = east, z = south, meters)", color="w")
    ax.tick_params(colors="#888")
    fig.patch.set_facecolor("#1b1f24")
    fig.savefig(args.preview, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"\nDone. Assets in {args.out}\nPreview: {args.preview}")


if __name__ == "__main__":
    main()
