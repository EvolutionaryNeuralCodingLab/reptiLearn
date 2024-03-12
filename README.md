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
    number = {2},
}
```

