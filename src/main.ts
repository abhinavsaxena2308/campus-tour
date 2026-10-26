import * as THREE from "three";
import { loadGeometry, loadJSON } from "./game/assets";
import type { Meta } from "./game/assets";
import { FlyCamera } from "./game/flycam";
import { addBall, addStaticTrimesh, createPhysics, FIXED_DT } from "./game/physics";

const BASE = import.meta.env.BASE_URL;
const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const loadingEl = el("loading");
const loadingText = el("loadingText");
const loadingBar = el("loadingBar");
const hudEl = el("hud");
const hintEl = el("hint");

// ---------------------------------------------------------------- renderer
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
document.body.prepend(renderer.domElement);

const SKY = 0x9fc5e8;
const scene = new THREE.Scene();
scene.background = new THREE.Color(SKY);
scene.fog = new THREE.Fog(SKY, 500, 2200);

// near = 0.5 keeps depth precision good enough for the thin road/grass overlays
const camera = new THREE.PerspectiveCamera(65, innerWidth / innerHeight, 0.5, 4000);
const fly = new FlyCamera(camera, renderer.domElement);

scene.add(new THREE.HemisphereLight(0xcfe3ff, 0x4d5a3a, 1.0));
const sun = new THREE.DirectionalLight(0xfff2d6, 2.4);
sun.position.set(300, 450, 150);
scene.add(sun);

// Big ground plane so the edge of the terrain square is not a void.
const apron = new THREE.Mesh(
  new THREE.PlaneGeometry(8000, 8000).rotateX(-Math.PI / 2),
  new THREE.MeshStandardMaterial({ color: 0x59693f, roughness: 1 }),
);
apron.position.y = -0.5;
scene.add(apron);

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ---------------------------------------------------------------- loading
const manager = new THREE.LoadingManager();
manager.onProgress = (_url, loaded, total) => {
  loadingBar.style.width = `${(loaded / total) * 100}%`;
};

function overlay(
  geo: THREE.BufferGeometry,
  color: number,
  order: number,
  extra: THREE.MeshStandardMaterialParameters = {},
): THREE.Mesh {
  const mat = new THREE.MeshStandardMaterial({
    color,
    roughness: 1,
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
    ...extra,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = order;
  return mesh;
}

async function boot(): Promise<void> {
  loadingText.textContent = "Loading campus…";
  const [meta, terrainGeo, buildingsGeo, roadsGeo, greensGeo, waterGeo, physics] = await Promise.all([
    loadJSON<Meta>(`${BASE}data/meta.json`),
    loadGeometry(`${BASE}data/terrain.glb`, manager),
    loadGeometry(`${BASE}data/buildings.glb`, manager),
    loadGeometry(`${BASE}data/roads.glb`, manager),
    loadGeometry(`${BASE}data/greens.glb`, manager),
    loadGeometry(`${BASE}data/water.glb`, manager),
    createPhysics(),
  ]);

  // ---- visuals
  const terrain = new THREE.Mesh(
    terrainGeo,
    new THREE.MeshStandardMaterial({ color: 0x8f9a6c, roughness: 1 }),
  );
  const buildings = new THREE.Mesh(
    buildingsGeo,
    new THREE.MeshStandardMaterial({ color: 0xe4d6b0, roughness: 0.9 }),
  );
  scene.add(
    terrain,
    overlay(greensGeo, 0x4f8f4a, 1),
    overlay(roadsGeo, 0x4a4e55, 2),
    overlay(waterGeo, 0x3b8fd0, 3, { transparent: true, opacity: 0.88, roughness: 0.15 }),
    buildings,
  );

  // ---- colliders (terrain + buildings are static triangle meshes)
  const t0 = performance.now();
  addStaticTrimesh(physics, terrainGeo);
  addStaticTrimesh(physics, buildingsGeo);
  console.log(`colliders built in ${(performance.now() - t0).toFixed(0)} ms`);

  // ---- ground height under (x, z): ray straight down onto the terrain mesh
  const ray = new THREE.Raycaster();
  const rayOrigin = new THREE.Vector3();
  const DOWN = new THREE.Vector3(0, -1, 0);
  const groundY = (x: number, z: number): number => {
    ray.set(rayOrigin.set(x, 2000, z), DOWN);
    const hit = ray.intersectObject(terrain, false)[0];
    return hit ? hit.point.y : 0;
  };

  // ---- balls (physics test objects)
  interface Ball {
    mesh: THREE.Mesh;
    body: ReturnType<typeof addBall>;
    prevPos: THREE.Vector3;
    curPos: THREE.Vector3;
    prevQuat: THREE.Quaternion;
    curQuat: THREE.Quaternion;
  }
  const balls: Ball[] = [];
  const BALL_R = 1.5;
  const MAX_BALLS = 80;
  const ballGeo = new THREE.SphereGeometry(BALL_R, 24, 16);
  const dir = new THREE.Vector3();

  const readBody = (b: Ball): void => {
    const p = b.body.translation();
    const q = b.body.rotation();
    b.curPos.set(p.x, p.y, p.z);
    b.curQuat.set(q.x, q.y, q.z, q.w);
  };

  const removeBall = (i: number): void => {
    const b = balls[i];
    physics.world.removeRigidBody(b.body);
    scene.remove(b.mesh);
    (b.mesh.material as THREE.Material).dispose();
    balls.splice(i, 1);
  };

  const dropBall = (): void => {
    camera.getWorldDirection(dir);
    ray.set(camera.position, dir);
    const hit = ray.intersectObjects([terrain, buildings], false)[0];
    const target = hit ? hit.point.clone() : camera.position.clone().addScaledVector(dir, 25);
    const y = target.y + 30;
    const body = addBall(physics, target.x, y, target.z, BALL_R);
    const mesh = new THREE.Mesh(
      ballGeo,
      new THREE.MeshStandardMaterial({ color: new THREE.Color().setHSL(Math.random(), 0.75, 0.55), roughness: 0.5 }),
    );
    mesh.position.set(target.x, y, target.z);
    scene.add(mesh);
    const ball: Ball = {
      mesh,
      body,
      prevPos: new THREE.Vector3(),
      curPos: new THREE.Vector3(),
      prevQuat: new THREE.Quaternion(),
      curQuat: new THREE.Quaternion(),
    };
    readBody(ball);
    ball.prevPos.copy(ball.curPos);
    ball.prevQuat.copy(ball.curQuat);
    balls.push(ball);
    if (balls.length > MAX_BALLS) removeBall(0);
  };

  // ---- start position: south-west corner, looking north-east over the campus
  const start = { x: -250, z: 250, yaw: -Math.PI / 4, pitch: -0.4 };
  const resetCamera = (): void =>
    fly.place(start.x, groundY(start.x, start.z) + 130, start.z, start.yaw, start.pitch);
  resetCamera();

  let showHud = true;
  addEventListener("keydown", (e) => {
    if (e.repeat) return;
    if (e.code === "KeyB") dropBall();
    if (e.code === "KeyR") resetCamera();
    if (e.code === "KeyH") {
      showHud = !showHud;
      hudEl.style.display = showHud ? "" : "none";
    }
  });

  // ---- main loop
  let acc = 0;
  let last = performance.now();
  let frames = 0;
  let fpsClock = last;
  let fps = 0;

  renderer.setAnimationLoop((now: number) => {
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;

    fly.update(dt);
    const g = groundY(camera.position.x, camera.position.z);
    if (camera.position.y < g + 2) camera.position.y = g + 2; // stay above the ground

    // fixed-timestep physics
    acc += dt;
    while (acc >= FIXED_DT) {
      for (const b of balls) {
        b.prevPos.copy(b.curPos);
        b.prevQuat.copy(b.curQuat);
      }
      physics.world.step();
      for (const b of balls) readBody(b);
      acc -= FIXED_DT;
    }
    // interpolate the render pose between the last two physics states
    const alpha = acc / FIXED_DT;
    for (let i = balls.length - 1; i >= 0; i--) {
      const b = balls[i];
      if (b.curPos.y < -100) {
        removeBall(i); // fell out of the world
        continue;
      }
      b.mesh.position.lerpVectors(b.prevPos, b.curPos, alpha);
      b.mesh.quaternion.slerpQuaternions(b.prevQuat, b.curQuat, alpha);
    }

    renderer.render(scene, camera);

    // HUD
    frames++;
    if (now - fpsClock >= 500) {
      fps = (frames * 1000) / (now - fpsClock);
      frames = 0;
      fpsClock = now;
      const p = camera.position;
      hudEl.textContent =
        `FPS ${fps.toFixed(0)}   triangles ${(renderer.info.render.triangles / 1000).toFixed(1)}k\n` +
        `pos  x ${p.x.toFixed(0)}  y ${p.y.toFixed(0)}  z ${p.z.toFixed(0)}   (ground ${g.toFixed(1)})\n` +
        `balls ${balls.length}   speed ${fly.speed.toFixed(0)} m/s\n\n` +
        `WASD move   Q/E down/up   Shift fast   Wheel speed\n` +
        `B drop ball   R reset view   H hide this`;
    }
    hintEl.classList.toggle("hidden", fly.locked);
  });

  loadingEl.classList.add("done");
  console.log(
    `campus ready: ${meta.counts.buildingMeshes} buildings, ${meta.counts.roadSurfaces} road surfaces`,
  );
}

boot().catch((err: unknown) => {
  console.error(err);
  loadingText.innerHTML = "";
  const box = document.createElement("div");
  box.className = "err";
  box.textContent = `Failed to load:\n${err instanceof Error ? err.message : String(err)}`;
  loadingText.append(box);
});
