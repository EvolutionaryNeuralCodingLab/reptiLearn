import {
    Group,
    Mesh,
    MeshBasicMaterial,
    NearestFilter,
    PlaneGeometry,
    SRGBColorSpace,
    TextureLoader,
} from 'three';

import turtleUrl from './turtle.png';

/** Flat pixel-art turtle. Local +X is the head, before the scene yaws it. */
export const makeTurtle = (onReady) => {
    const texture = new TextureLoader().load(turtleUrl, () => {
        if (onReady) onReady();
    });
    texture.magFilter = NearestFilter;
    texture.minFilter = NearestFilter;
    texture.generateMipmaps = false;
    texture.colorSpace = SRGBColorSpace;
    const span = 1.2;
    const mesh = new Mesh(
        new PlaneGeometry(span, span),
        new MeshBasicMaterial({
            map: texture,
            transparent: true,
            alphaTest: 0.05,
        }),
    );
    mesh.rotation.x = -Math.PI / 2;
    const board = new Group();
    board.rotation.y = -Math.PI / 2;
    board.add(mesh);
    const animal = new Group();
    animal.add(board);
    return animal;
};
