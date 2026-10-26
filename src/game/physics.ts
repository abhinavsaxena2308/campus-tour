import RAPIER from "@dimforge/rapier3d-compat";
import type { BufferGeometry } from "three";

/** Physics always advances in fixed steps; rendering interpolates between them. */
export const FIXED_DT = 1 / 60;

export interface Physics {
  RAPIER: typeof RAPIER;
  world: RAPIER.World;
}

export async function createPhysics(): Promise<Physics> {
  await RAPIER.init();
  const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  world.timestep = FIXED_DT;
  return { RAPIER, world };
}

/** Immovable triangle-mesh collider built from a three.js geometry (already in world space). */
export function addStaticTrimesh(p: Physics, geo: BufferGeometry): RAPIER.Collider {
  const pos = geo.getAttribute("position");
  const vertices = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    vertices[i * 3] = pos.getX(i);
    vertices[i * 3 + 1] = pos.getY(i);
    vertices[i * 3 + 2] = pos.getZ(i);
  }
  let indices: Uint32Array;
  if (geo.index) {
    indices = Uint32Array.from(geo.index.array as ArrayLike<number>);
  } else {
    indices = new Uint32Array(pos.count);
    for (let i = 0; i < pos.count; i++) indices[i] = i;
  }
  const body = p.world.createRigidBody(p.RAPIER.RigidBodyDesc.fixed());
  return p.world.createCollider(p.RAPIER.ColliderDesc.trimesh(vertices, indices), body);
}

export function addBall(
  p: Physics,
  x: number,
  y: number,
  z: number,
  radius: number,
): RAPIER.RigidBody {
  const body = p.world.createRigidBody(
    p.RAPIER.RigidBodyDesc.dynamic().setTranslation(x, y, z).setLinearDamping(0.05).setAngularDamping(0.3),
  );
  p.world.createCollider(
    p.RAPIER.ColliderDesc.ball(radius).setRestitution(0.45).setFriction(0.8).setDensity(1.0),
    body,
  );
  return body;
}
