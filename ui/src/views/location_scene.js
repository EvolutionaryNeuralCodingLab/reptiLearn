import React from 'react';
import {
    Scene,
    PerspectiveCamera,
    WebGLRenderer,
    Color,
    HemisphereLight,
    DirectionalLight,
    Mesh,
    MeshBasicMaterial,
    PlaneGeometry,
    Group,
    BufferGeometry,
    Float32BufferAttribute,
    Line,
    LineBasicMaterial,
    NearestFilter,
    LinearFilter,
    RepeatWrapping,
    SRGBColorSpace,
    TextureLoader,
} from 'three';

import { fieldPoint, fieldTrail } from './location_field.js';
import { makeTurtle } from './location_turtle.js';
import arenaUrl from './arena.png';
import openedDoorUrl from './opened_door.png';
import closedDoorUrl from './closed_door.png';
import magnetArrowUrl from './magnet_arrow.png';

const SCALE = 100;

const toWorld = (x, y) => ({
    x: (x - 480) / SCALE,
    z: (y - 360) / SCALE,
});

/** Water gaps in arena.png, fractions of the picture, origin at the top left. */
const DOOR_GAPS = {
    backLeft: [0.347, 0.302, 0.413, 0.360],
    backRight: [0.553, 0.300, 0.631, 0.362],
    frontLeft: [0.317, 0.728, 0.382, 0.780],
    frontRight: [0.614, 0.728, 0.682, 0.782],
};

// Opaque artwork inside the door files, as a fraction of each canvas.
const DOOR_ART = { x0: 0.22, y0: 0.12, x1: 0.78, y1: 0.86 };

const punchCheckerboard = (texture) => {
    const image = texture.image;
    const canvas = document.createElement('canvas');
    canvas.width = image.width;
    canvas.height = image.height;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(image, 0, 0);
    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    const pixels = frame.data;
    for (let i = 0; i < pixels.length; i += 4) {
        const red = pixels[i];
        const green = pixels[i + 1];
        const blue = pixels[i + 2];
        const max = Math.max(red, green, blue);
        const min = Math.min(red, green, blue);
        if (max - min < 28 && min > 170) pixels[i + 3] = 0;
    }
    context.putImageData(frame, 0, 0);
    texture.image = canvas;
    texture.magFilter = NearestFilter;
    texture.minFilter = NearestFilter;
    texture.generateMipmaps = false;
    texture.colorSpace = SRGBColorSpace;
    texture.needsUpdate = true;
};

const loadDoorTexture = (url, onReady) => new TextureLoader().load(url, (texture) => {
    punchCheckerboard(texture);
    if (onReady) onReady();
});

const BRIDGE_SCALE = 1.4;

const makeBridge = (box, texture) => {
    const [u1, v1, u2, v2] = box;
    const width = ((u2 - u1) / (DOOR_ART.x1 - DOOR_ART.x0)) * 9.6 * BRIDGE_SCALE;
    const depth = ((v2 - v1) / (DOOR_ART.y1 - DOOR_ART.y0)) * 7.2 * BRIDGE_SCALE;
    const mesh = new Mesh(
        new PlaneGeometry(width, depth),
        new MeshBasicMaterial({ map: texture, transparent: true, alphaTest: 0.15 }),
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.renderOrder = 1;
    const point = toWorld(((u1 + u2) / 2) * 960, ((v1 + v2) / 2) * 720);
    mesh.position.set(point.x, 0.04, point.z);
    return mesh;
};

const buildArena = (scene, onReady) => {
    const texture = new TextureLoader().load(arenaUrl, () => {
        if (onReady) onReady();
    });
    texture.magFilter = NearestFilter;
    texture.minFilter = NearestFilter;
    texture.generateMipmaps = false;
    texture.colorSpace = SRGBColorSpace;
    const ground = new Mesh(
        new PlaneGeometry(960 / SCALE, 720 / SCALE),
        new MeshBasicMaterial({ map: texture }),
    );
    ground.rotation.x = -Math.PI / 2;
    scene.add(ground);

    const magnetMap = new TextureLoader().load(magnetArrowUrl, () => {
        if (onReady) onReady();
    });
    magnetMap.magFilter = LinearFilter;
    magnetMap.minFilter = LinearFilter;
    magnetMap.generateMipmaps = false;
    magnetMap.colorSpace = SRGBColorSpace;
    magnetMap.wrapS = RepeatWrapping;
    // The file points right. Forward keeps that; reverse mirrors it to the left.
    const magnet = new Mesh(
        new PlaneGeometry(2.2, 2.2 / 3),
        new MeshBasicMaterial({
            map: magnetMap,
            transparent: true,
            alphaTest: 0.04,
            depthWrite: false,
        }),
    );
    magnet.rotation.x = -Math.PI / 2;
    magnet.renderOrder = 2;
    const magnetPoint = toWorld(465, 140);
    magnet.position.set(magnetPoint.x, 0.08, magnetPoint.z);
    scene.add(magnet);

    const closedDoor = loadDoorTexture(closedDoorUrl, onReady);
    const openedDoor = loadDoorTexture(openedDoorUrl, onReady);
    const bridges = {};
    Object.entries(DOOR_GAPS).forEach(([name, box]) => {
        bridges[name] = makeBridge(box, openedDoor);
        scene.add(bridges[name]);
    });

    return { magnet, closedDoor, openedDoor, bridges };
};

const disposeObject = (object) => {
    const maps = new Set();
    object.traverse((child) => {
        if (child.geometry) child.geometry.dispose();
        if (child.material) {
            const materials = Array.isArray(child.material) ? child.material : [child.material];
            materials.forEach((material) => {
                if (material.map && !maps.has(material.map)) {
                    maps.add(material.map);
                    material.map.dispose();
                }
                material.dispose();
            });
        }
    });
};

const LocationScene = ({
    width,
    height,
    zones,
    doors,
    trail,
    sample,
    facing,
    held,
    magnetDirection,
    foodCount,
}) => {
    const mountRef = React.useRef(null);
    const apiRef = React.useRef(null);
    const [failed, setFailed] = React.useState(false);

    React.useEffect(() => {
        const host = mountRef.current;
        if (!host) return undefined;
        let renderer;
        try {
            renderer = new WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' });
        } catch (error) {
            setFailed(true);
            return undefined;
        }
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        renderer.setSize(width, height, false);
        renderer.domElement.style.width = '100%';
        renderer.domElement.style.height = '100%';
        renderer.domElement.style.display = 'block';
        const scene = new Scene();
        scene.background = new Color('#1a7eb8');
        scene.add(new HemisphereLight('#d6eaf8', '#c4a574', 0.85));
        const sun = new DirectionalLight('#fff6e0', 0.9);
        sun.position.set(-4, 10, 3);
        scene.add(sun);

        const redraw = () => {
            const api = apiRef.current;
            if (api) api.renderer.render(api.scene, api.camera);
        };
        const parts = buildArena(scene, redraw);
        const turtle = makeTurtle(redraw);
        scene.add(turtle);
        const trailGroup = new Group();
        scene.add(trailGroup);

        const camera = new PerspectiveCamera(42, width / Math.max(height, 1), 0.1, 80);
        camera.position.set(0, 8.6, 4.4);
        camera.lookAt(0, 0, 0.15);

        host.appendChild(renderer.domElement);
        apiRef.current = { renderer, scene, camera, turtle, trailGroup, ...parts };
        renderer.render(scene, camera);

        return () => {
            disposeObject(scene);
            renderer.dispose();
            renderer.forceContextLoss();
            if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
            apiRef.current = null;
        };
        // The scene is created once for this canvas size's first mount.
        // Size and animal updates are applied below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    React.useEffect(() => {
        const api = apiRef.current;
        if (!api || width <= 0 || height <= 0) return;
        api.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        api.renderer.setSize(width, height, false);
        api.renderer.domElement.style.width = '100%';
        api.renderer.domElement.style.height = '100%';
        api.camera.aspect = width / height;
        api.camera.updateProjectionMatrix();

        const here = fieldPoint(sample, zones);
        api.turtle.visible = Boolean(here);
        if (here) {
            const point = toWorld(here.x, here.y);
            api.turtle.position.set(point.x, 0.22, point.z);
            const angle = facing ? Math.atan2(facing.dy, facing.dx) : 0;
            api.turtle.rotation.y = -angle;
            api.turtle.traverse((child) => {
                if (child.material) child.material.opacity = held ? 0.4 : 1;
                if (child.material) child.material.transparent = Boolean(held);
            });
        }

        const pointingRight = magnetDirection === 'forward';
        api.magnet.visible = magnetDirection === 'forward' || magnetDirection === 'reverse';
        api.magnet.material.map.repeat.x = pointingRight ? 1 : -1;
        api.magnet.material.map.offset.x = pointingRight ? 0 : 1;

        // closed_door.png is the solid bridge and means the door is open.
        // opened_door.png is the split bridge and means the door is closed.
        const placeDoor = (name, open) => {
            const mesh = api.bridges[name];
            mesh.material.map = open ? api.closedDoor : api.openedDoor;
        };
        placeDoor('backLeft', Boolean(doors?.backLeft));
        placeDoor('backRight', Boolean(doors?.backRight));
        placeDoor('frontLeft', Boolean(doors?.frontLeft));
        placeDoor('frontRight', Boolean(doors?.frontRight));

        while (api.trailGroup.children.length) {
            const line = api.trailGroup.children[0];
            api.trailGroup.remove(line);
            line.geometry.dispose();
            line.material.dispose();
        }
        fieldTrail(trail, zones).forEach((segment) => {
            const positions = [];
            segment.forEach((point) => {
                const world = toWorld(point.x, point.y);
                positions.push(world.x, 0.16, world.z);
            });
            const geometry = new BufferGeometry();
            geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
            api.trailGroup.add(new Line(geometry, new LineBasicMaterial({ color: '#196f3d' })));
        });

        api.renderer.render(api.scene, api.camera);
    }, [width, height, zones, doors, trail, sample, facing, held, magnetDirection]);

    return (
        <div className="relative overflow-hidden" style={{ width, height }}>
            <div ref={mountRef} className="w-full h-full" />
            {failed && (
                <div className="absolute inset-0 flex items-center justify-center text-white">
                    This browser could not start the 3D view.
                </div>
            )}
            {!failed && !sample && (
                <div className="absolute left-1/2 top-1/3 -translate-x-1/2 text-white text-sm">
                    No detection
                </div>
            )}
            <div className="absolute top-2 left-2 bg-[#f8f5ee] border-2 border-[#2c3e50] rounded-md px-2 py-1 text-xs shadow">
                <div className="font-bold text-[#1a5276]">TURTLE</div>
                <div className="font-bold text-[#6e5432]">{`Food: ${foodCount}`}</div>
            </div>
            <div className="absolute top-2 right-2 bg-[#f8f5ee] border-2 border-[#2c3e50] rounded-md text-xs shadow overflow-hidden">
                <div className="bg-[#1a5276] text-white font-bold text-center px-3 py-0.5">DOORS</div>
                <div className="px-2 py-1">
                    <div>
                        Left{' '}
                        <span className={doors?.backLeft ? 'text-[#196f3d] font-bold' : 'text-[#922b21] font-bold'}>
                            {doors?.backLeft ? 'OPEN' : 'CLOSED'}
                        </span>
                    </div>
                    <div>
                        Right{' '}
                        <span className={doors?.backRight ? 'text-[#196f3d] font-bold' : 'text-[#922b21] font-bold'}>
                            {doors?.backRight ? 'OPEN' : 'CLOSED'}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default LocationScene;
