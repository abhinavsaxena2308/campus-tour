import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
document.body.style.margin = "0";
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87ceeb);
scene.fog = new THREE.Fog(0x87ceeb, 200, 1200);

const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.1, 3000);
camera.position.set(30, 25, 40);

scene.add(new THREE.HemisphereLight(0xffffff, 0x445544, 1));
const sun = new THREE.DirectionalLight(0xffffff, 2);
sun.position.set(100, 200, 50);
scene.add(sun);

scene.add(new THREE.GridHelper(500, 50));
const cube = new THREE.Mesh(
  new THREE.BoxGeometry(5, 5, 5),
  new THREE.MeshStandardMaterial({ color: 0xe8d9a8 })
);
cube.position.y = 2.5;
scene.add(cube);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 2, 0);

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

renderer.setAnimationLoop(() => {
  cube.rotation.y += 0.005;
  controls.update();
  renderer.render(scene, camera);
});