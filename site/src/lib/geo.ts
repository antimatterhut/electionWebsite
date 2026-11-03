// Geometry helpers shared by the national Canvas map and the state SVG map.
import { Delaunay } from 'd3-delaunay';
import { geoPath } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import type { GeometryCollection, Topology } from 'topojson-specification';
import type { Feature, FeatureCollection, Geometry } from 'geojson';

export const ATLAS_W = 975; // us-atlas Albers USA extent (pixel units)
export const ATLAS_H = 610;

export interface Props { geoid: string; name: string; state: string; race?: boolean }
export type Feat = Feature<Geometry, Props>;

export interface Shape {
  geoid: string;
  name: string;
  state: string;
  d: string;
  centroid: [number, number];
  path?: Path2D;
}

const pathGen = geoPath(); // data are already projected

export function features(topo: Topology, object: string): Feat[] {
  const o = topo.objects[object] as GeometryCollection<Props> | undefined;
  if (!o) throw new Error(`topology has no object "${object}"`);
  return (feature(topo, o) as unknown as FeatureCollection<Geometry, Props>).features as Feat[];
}

export function toShapes(feats: Feat[], withPath = false): Shape[] {
  return feats.map((f) => {
    const d = pathGen(f) ?? '';
    const c = pathGen.centroid(f);
    return {
      geoid: f.properties.geoid, name: f.properties.name, state: f.properties.state, d,
      centroid: [c[0]!, c[1]!] as [number, number],
      path: withPath && typeof Path2D !== 'undefined' ? new Path2D(d) : undefined
    };
  });
}

export function borders(topo: Topology, object: string, onlyInterior = true): string {
  const o = topo.objects[object] as GeometryCollection<Props>;
  return pathGen(mesh(topo, o, onlyInterior ? (a, b) => a !== b : undefined)) ?? '';
}

export function bounds(feats: Feat[]): [[number, number], [number, number]] {
  const fc: FeatureCollection<Geometry, Props> = { type: 'FeatureCollection', features: feats };
  return pathGen.bounds(fc) as [[number, number], [number, number]];
}

/** Nearest-centroid lookup refined by exact point-in-path tests on the closest candidates. */
export class HitTester {
  private delaunay: Delaunay<[number, number]>;
  constructor(private shapes: Shape[], private ctx: CanvasRenderingContext2D | null) {
    this.delaunay = Delaunay.from(shapes.map((s) => s.centroid));
  }

  /** x, y in topology (atlas) units. Returns the shape under the point, else the nearest centroid within `slack`. */
  find(x: number, y: number, slack = 10): Shape | null {
    if (!this.shapes.length) return null;
    const i = this.delaunay.find(x, y);
    const cands = new Set<number>([i, ...this.delaunay.neighbors(i)]);
    if (this.ctx) {
      this.ctx.save();
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      for (const k of cands) {
        const s = this.shapes[k]!;
        if (s.path && this.ctx.isPointInPath(s.path, x, y)) { this.ctx.restore(); return s; }
      }
      this.ctx.restore();
    }
    const s = this.shapes[i]!;
    return Math.hypot(s.centroid[0] - x, s.centroid[1] - y) <= slack ? s : null;
  }
}

/** Convert a pointer position within an element of CSS size (w, h) to atlas units (the map is drawn to fit). */
export function toAtlas(px: number, py: number, w: number, h: number): [number, number] {
  const s = Math.min(w / ATLAS_W, h / ATLAS_H);
  const ox = (w - ATLAS_W * s) / 2, oy = (h - ATLAS_H * s) / 2;
  return [(px - ox) / s, (py - oy) / s];
}
