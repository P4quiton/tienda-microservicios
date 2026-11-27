import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, signal } from '@angular/core';

@Component({
  selector: 'app-intro-logo',
  template: `
    <div class="intro" [class.intro--salida]="saliendo()" aria-hidden="true">
      <div class="intro__aura"></div>
      <div class="intro__marca" [class.intro__marca--3d]="lista3d()">
        <img class="intro__fallback" src="/brand/nebula-emblema.svg" alt="" />
        <canvas #lienzo class="intro__canvas"></canvas>
      </div>
      <span class="intro__nombre">Nébula</span>
      <span class="intro__linea"></span>
    </div>
  `,
  styleUrl: './intro-logo.css',
})
export class IntroLogo implements AfterViewInit, OnDestroy {
  @ViewChild('lienzo', { static: true }) private lienzo!: ElementRef<HTMLCanvasElement>;

  protected readonly saliendo = signal(false);
  protected readonly lista3d = signal(false);

  private disposed = false;
  private animationFrame = 0;
  private timers: number[] = [];
  private renderer?: import('three').WebGLRenderer;
  private scene?: import('three').Scene;
  private camera?: import('three').PerspectiveCamera;
  private emblema?: import('three').Group;
  private resizeObserver?: ResizeObserver;

  async ngAfterViewInit(): Promise<void> {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? true) {
      this.terminar(180);
      return;
    }

    try {
      await this.crearEscena();
      if (!this.disposed) this.animar();
    } catch {
      // El SVG local permanece visible con una transición CSS si WebGL no está disponible.
      this.terminar(1800);
    }
  }

  ngOnDestroy(): void {
    this.disposed = true;
    cancelAnimationFrame(this.animationFrame);
    this.timers.forEach(clearTimeout);
    this.resizeObserver?.disconnect();
    this.liberarEscena();
  }

  private async crearEscena(): Promise<void> {
    const THREE = await import('three');
    const { SVGLoader } = await import('three/addons/loaders/SVGLoader.js');
    const { RoomEnvironment } = await import('three/addons/environments/RoomEnvironment.js');
    if (this.disposed) return;

    const canvas = this.lienzo.nativeElement;
    this.renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.setSize(240, 240, false);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    this.scene = new THREE.Scene();
    const room = new RoomEnvironment();
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(room, 0.04).texture;
    room.dispose();
    pmrem.dispose();
    this.camera = new THREE.PerspectiveCamera(33, 1, 0.1, 40);
    this.camera.position.set(0, 0, 7.4);

    this.scene.add(new THREE.AmbientLight(0x91dfff, 2.2));
    const key = new THREE.DirectionalLight(0xe6faff, 5);
    key.position.set(-3, 4, 6);
    this.scene.add(key);
    const cyanRim = new THREE.PointLight(0x00d9ff, 24, 12);
    cyanRim.position.set(3, -1, 3);
    this.scene.add(cyanRim);
    const blueRim = new THREE.PointLight(0x3d65ff, 18, 12);
    blueRim.position.set(-3, -2, 2);
    this.scene.add(blueRim);

    const response = await fetch('/brand/nebula-emblema.svg');
    if (!response.ok) throw new Error('No se pudo cargar el emblema Nébula.');
    const svg = new SVGLoader().parse(await response.text());
    const group = new THREE.Group();
    const tonos = [0x2257b5, 0x19d9f5, 0x4c8dff];

    svg.paths.forEach((path, index) => {
      const shapes = path.toShapes();
      if (!shapes.length) return;
      const geometry = new THREE.ExtrudeGeometry(shapes, {
        depth: 8,
        bevelEnabled: true,
        bevelSegments: 4,
        steps: 1,
        bevelSize: 0.85,
        bevelThickness: 0.85,
        curveSegments: 24,
      });
      geometry.translate(-32, -32, -4);
      geometry.scale(0.052, -0.052, 0.052);
      geometry.computeVertexNormals();

      const material = new THREE.MeshPhysicalMaterial({
        color: tonos[index % tonos.length],
        metalness: 0.2,
        roughness: 0.12,
        transmission: 0.56,
        thickness: 1.1,
        clearcoat: 1,
        clearcoatRoughness: 0.08,
        ior: 1.42,
        emissive: tonos[index % tonos.length],
        emissiveIntensity: 0.08,
        side: THREE.DoubleSide,
      });
      group.add(new THREE.Mesh(geometry, material));
    });

    this.emblema = group;
    group.scale.setScalar(0.82);
    group.rotation.set(0.08, -1.82, -0.08);
    this.scene.add(group);
    this.lista3d.set(true);

    this.resizeObserver = new ResizeObserver(() => {
      if (!this.renderer || !this.camera) return;
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    });
    this.resizeObserver.observe(canvas);
  }

  private animar(): void {
    if (!this.renderer || !this.scene || !this.camera || !this.emblema) return;
    const inicio = performance.now();
    const duracion = 2150;

    const cuadro = (ahora: number) => {
      if (this.disposed || !this.renderer || !this.scene || !this.camera || !this.emblema) return;
      const t = Math.min(1, (ahora - inicio) / duracion);
      const suave = 1 - Math.pow(1 - t, 4);
      this.emblema.rotation.y = -1.82 * (1 - suave) + Math.sin(t * Math.PI * 2) * 0.025;
      this.emblema.rotation.x = 0.08 + Math.sin(t * Math.PI) * 0.07;
      this.emblema.rotation.z = -0.08 * (1 - suave);
      const rebote = 1 + Math.sin(Math.min(1, t * 1.1) * Math.PI) * 0.035;
      this.emblema.scale.setScalar((0.82 + suave * 0.18) * rebote);
      this.emblema.position.y = Math.sin(t * Math.PI * 1.4) * 0.11;
      this.renderer.render(this.scene, this.camera);

      if (t >= 1) {
        this.terminar(450);
        return;
      }
      this.animationFrame = requestAnimationFrame(cuadro);
    };

    this.animationFrame = requestAnimationFrame(cuadro);
  }

  private terminar(retardo: number): void {
    this.timers.push(window.setTimeout(() => this.saliendo.set(true), retardo));
    this.timers.push(window.setTimeout(() => {
      this.disposed = true;
      this.liberarEscena();
    }, retardo + 480));
  }

  private liberarEscena(): void {
    this.scene?.environment?.dispose();
    this.scene?.traverse((objeto) => {
      const malla = objeto as import('three').Mesh;
      malla.geometry?.dispose();
      const materiales = Array.isArray(malla.material) ? malla.material : [malla.material];
      materiales?.forEach((material) => material?.dispose());
    });
    this.renderer?.dispose();
    this.renderer = undefined;
    this.scene = undefined;
    this.camera = undefined;
    this.emblema = undefined;
  }
}
