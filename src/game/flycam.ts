import { MathUtils, Vector3 } from "three";
import type { PerspectiveCamera } from "three";

/** Free-fly debug camera: WASD move, Q/E (or C/Space) down/up, Shift = fast, wheel = speed. */
export class FlyCamera {
  readonly camera: PerspectiveCamera;
  private readonly el: HTMLElement;
  private readonly keys = new Set<string>();
  yaw = 0;
  pitch = 0;
  speed = 40; // meters per second
  private readonly fwd = new Vector3();
  private readonly right = new Vector3();
  private readonly move = new Vector3();

  constructor(camera: PerspectiveCamera, el: HTMLElement) {
    this.camera = camera;
    this.el = el;
    this.camera.rotation.order = "YXZ";

    el.addEventListener("click", () => {
      if (!this.locked) el.requestPointerLock();
    });
    addEventListener("mousemove", (e) => {
      if (!this.locked) return;
      this.yaw -= e.movementX * 0.0022;
      this.pitch = MathUtils.clamp(this.pitch - e.movementY * 0.0022, -1.55, 1.55);
    });
    addEventListener("keydown", (e) => this.keys.add(e.code));
    addEventListener("keyup", (e) => this.keys.delete(e.code));
    addEventListener("blur", () => this.keys.clear());
    addEventListener("wheel", (e) => {
      this.speed = MathUtils.clamp(this.speed * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 4, 400);
    });
  }

  get locked(): boolean {
    return document.pointerLockElement === this.el;
  }

  /** Teleport and aim. */
  place(x: number, y: number, z: number, yaw: number, pitch: number): void {
    this.camera.position.set(x, y, z);
    this.yaw = yaw;
    this.pitch = pitch;
    this.camera.rotation.set(pitch, yaw, 0);
  }

  isDown(code: string): boolean {
    return this.keys.has(code);
  }

  update(dt: number): void {
    this.camera.rotation.set(this.pitch, this.yaw, 0);

    this.camera.getWorldDirection(this.fwd);
    this.right.crossVectors(this.fwd, this.camera.up).normalize();
    this.move.set(0, 0, 0);
    if (this.keys.has("KeyW")) this.move.add(this.fwd);
    if (this.keys.has("KeyS")) this.move.sub(this.fwd);
    if (this.keys.has("KeyD")) this.move.add(this.right);
    if (this.keys.has("KeyA")) this.move.sub(this.right);
    if (this.keys.has("KeyE") || this.keys.has("Space")) this.move.y += 1;
    if (this.keys.has("KeyQ") || this.keys.has("KeyC")) this.move.y -= 1;

    if (this.move.lengthSq() > 0) {
      const boost = this.keys.has("ShiftLeft") || this.keys.has("ShiftRight") ? 4 : 1;
      this.move.normalize().multiplyScalar(this.speed * boost * dt);
      this.camera.position.add(this.move);
    }
  }
}
