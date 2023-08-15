Merlin Design Space Exploration Infrastructure
==============================================

Merlin DSE is a highly configurable automation infrastructure to free human
beings from manually tuning Merlin pragmas to achieve high performance.
It leverages a gradient-based search algorithm and performance bottleneck analysis
to quickly identify the high impact pragmas and focuses on them in order to give
users a decent QoR as soon as possible. In addition, the search process done by
the gradient-based search algorithm is easy to reason, so users can easily figure
out where to be further improved accordingly.

## Documentation

The Merlin DSE documents can be found
[here](https://falcon-computing.github.io/DSE).
It includes:

* Installation guide

* Tutorials

* Development guide

* API Reference

## System Requirements

* Python 3.6+

* Redis database

For MidEnd Testing,
1. Launch DSGenerator
2. Copy over output (rose__xxx.cpp and ds_info.json) to DSE working directory, rename rose__xxx.cpp to xxx.cpp
3. Run DSE
