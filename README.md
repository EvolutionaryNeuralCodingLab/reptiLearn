# ReptiLearn

__ReptiLearn__ is an open-source software system for building automated behavioral arenas, running closed-loop experiments based on realtime video analysis, and collecting behavioral data. 

__ReptiLearn__ was created to help us run continuous, long-term, learning experiments tailored to the specific needs and challenges posed by reptile model animals. 

![ReptiLearn user interface](/docs/images/reptilearn-ui.png)


## Main Features

- Synchronized video recording and real-time analysis from multiple video sources
- Control of various arena hardware components such as temperature sensors, lighting, and reward feeders
- Automate and run closed-loop behavioral experiments
- Web based interface for remote monitoring and control
- Highly extendable. Written purely in Python.

## Documentation

- [Getting started](docs/getting_started.md)
- [Building an arena](docs/build_arena.md)
- [Camera configuration](docs/camera_config.md)
- [Setting up the arena controller](docs/arena_setup.md)
- [Programming experiments](docs/programming_experiments.md)

:dizzy: For more information check out our [paper](https://dx.plos.org/10.1371/journal.pbio.3002411)

If you use ReptiLearn for your research please cite us!

```bibtex
@article{10.1371/journal.pbio.3002411,
    doi = {10.1371/journal.pbio.3002411},
    author = {Eisenberg, Tal AND Shein-Idelson, Mark},
    journal = {PLOS Biology},
    publisher = {Public Library of Science},
    title = {ReptiLearn: An automated home cage system for behavioral experiments in reptiles without human intervention},
    year = {2024},
    month = {02},
    volume = {22},
    url = {https://doi.org/10.1371/journal.pbio.3002411},
    pages = {1-27},
    abstract = {Understanding behavior and its evolutionary underpinnings is crucial for unraveling the complexities of brain function. Traditional approaches strive to reduce behavioral complexity by designing short-term, highly constrained behavioral tasks with dichotomous choices in which animals respond to defined external perturbation. In contrast, natural behaviors evolve over multiple time scales during which actions are selected through bidirectional interactions with the environment and without human intervention. Recent technological advancements have opened up new possibilities for experimental designs that more closely mirror natural behaviors by replacing stringent experimental control with accurate multidimensional behavioral analysis. However, these approaches have been tailored to fit only a small number of species. This specificity limits the experimental opportunities offered by species diversity. Further, it hampers comparative analyses that are essential for extracting overarching behavioral principles and for examining behavior from an evolutionary perspective. To address this limitation, we developed ReptiLearn—a versatile, low-cost, Python-based solution, optimized for conducting automated long-term experiments in the home cage of reptiles, without human intervention. In addition, this system offers unique features such as precise temperature measurement and control, live prey reward dispensers, engagement with touch screens, and remote control through a user-friendly web interface. Finally, ReptiLearn incorporates low-latency closed-loop feedback allowing bidirectional interactions between animals and their environments. Thus, ReptiLearn provides a comprehensive solution for researchers studying behavior in ectotherms and beyond, bridging the gap between constrained laboratory settings and natural behavior in nonconventional model systems. We demonstrate the capabilities of ReptiLearn by automatically training the lizard Pogona vitticeps on a complex spatial learning task requiring association learning, displaced reward learning, and reversal learning.},
    number = {2},
}
```

