import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { BufferGeometry, LoadingManager, Mesh, Object3D } from "three";

export interface Meta {
  originX: number;
  originY: number;
  originZ: number;
  terrain: { minX: number; maxX: number; minZ: number; maxZ: number; maxY: number };
  counts: Record<string, number>;
}

/** First mesh found in a loaded glTF scene, with its node transform baked in. */
export function firstGeometry(root: Object3D, name = "glb"): BufferGeometry {
  root.updateMatrixWorld(true);
  let found: Mesh | undefined;
  root.traverse((o) => {
    if (!found && (o as Mesh).isMesh) found = o as Mesh;
  });
  if (!found) throw new Error(`No mesh found in ${name}`);
  return found.geometry.clone().applyMatrix4(found.matrixWorld);
}

export async function loadGeometry(url: string, manager?: LoadingManager): Promise<BufferGeometry> {
  const gltf = await new GLTFLoader(manager).loadAsync(url);
  return firstGeometry(gltf.scene, url);
}

export async function loadJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return (await res.json()) as T;
}
