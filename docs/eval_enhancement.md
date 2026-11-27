# Enhancement Evaluation (Hard Mode)

- Index: `data/outputs/sample2/index_s0_e247p887` (`N=18` embeddings)
- Query result: `data/outputs/sample2/tx155_w6_atm_155/result.json` (`query_track_id=4`, `query_identity=person_pink`, `n_query_frames=5`)

## Identity Map Used

| track_id | identity | index_rows |
| ---: | --- | ---: |
| 1 | track_1 | 1 |
| 3 | track_3 | 3 |
| 4 | person_pink | 6 |
| 5 | track_5 | 1 |
| 7 | track_7 | 3 |
| 8 | track_8 | 3 |
| 10 | track_10 | 1 |
| 11 | person_pink | 6 |

### width=24px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.596 | 0.320 | 0.276 |
| lanczos_x2 | 1.000 | 1.000 | 0.564 | 0.311 | 0.253 |
| lanczos_x4 | 1.000 | 1.000 | 0.582 | 0.314 | 0.268 |

### width=24px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.000 | n/a | n/a | n/a | n/a |
| lanczos_x2 | 0.600 | 1.000 | 0.386 | 0.361 | 0.024 |
| lanczos_x4 | 0.400 | 1.000 | 0.404 | 0.369 | 0.035 |

### width=24px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.496 | 0.304 | 0.192 |
| lanczos_x2 | 0.800 | 1.000 | 0.413 | 0.305 | 0.108 |
| lanczos_x4 | 1.000 | 1.000 | 0.441 | 0.311 | 0.129 |

### width=24px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.200 | 0.000 | 0.428 | 0.430 | -0.002 |
| lanczos_x2 | 0.600 | 0.000 | 0.271 | 0.318 | -0.046 |
| lanczos_x4 | 0.600 | 0.000 | 0.266 | 0.316 | -0.050 |

### width=24px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.000 | n/a | n/a | n/a | n/a |
| lanczos_x2 | 0.000 | n/a | n/a | n/a | n/a |
| lanczos_x4 | 0.000 | n/a | n/a | n/a | n/a |

### width=30px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.629 | 0.299 | 0.330 |
| lanczos_x2 | 1.000 | 1.000 | 0.590 | 0.280 | 0.311 |
| lanczos_x4 | 1.000 | 1.000 | 0.589 | 0.279 | 0.310 |

### width=30px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.600 | 0.667 | 0.443 | 0.428 | 0.014 |
| lanczos_x2 | 1.000 | 0.600 | 0.404 | 0.396 | 0.008 |
| lanczos_x4 | 0.800 | 0.500 | 0.394 | 0.382 | 0.012 |

### width=30px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.612 | 0.297 | 0.315 |
| lanczos_x2 | 1.000 | 1.000 | 0.558 | 0.319 | 0.239 |
| lanczos_x4 | 1.000 | 1.000 | 0.563 | 0.309 | 0.254 |

### width=30px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.400 | 0.000 | 0.405 | 0.454 | -0.049 |
| lanczos_x2 | 0.600 | 0.333 | 0.383 | 0.401 | -0.019 |
| lanczos_x4 | 0.800 | 0.250 | 0.313 | 0.332 | -0.019 |

### width=30px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.000 | n/a | n/a | n/a | n/a |
| lanczos_x2 | 0.400 | 0.500 | 0.282 | 0.273 | 0.008 |
| lanczos_x4 | 0.000 | n/a | n/a | n/a | n/a |

### width=36px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.645 | 0.294 | 0.351 |
| lanczos_x2 | 1.000 | 1.000 | 0.623 | 0.290 | 0.334 |
| lanczos_x4 | 1.000 | 1.000 | 0.630 | 0.292 | 0.339 |

### width=36px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 0.600 | 0.470 | 0.466 | 0.004 |
| lanczos_x2 | 1.000 | 0.800 | 0.408 | 0.379 | 0.029 |
| lanczos_x4 | 1.000 | 0.800 | 0.410 | 0.382 | 0.028 |

### width=36px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.623 | 0.290 | 0.333 |
| lanczos_x2 | 1.000 | 1.000 | 0.608 | 0.281 | 0.327 |
| lanczos_x4 | 1.000 | 1.000 | 0.610 | 0.290 | 0.320 |

### width=36px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.600 | 0.333 | 0.437 | 0.431 | 0.006 |
| lanczos_x2 | 1.000 | 0.600 | 0.402 | 0.381 | 0.021 |
| lanczos_x4 | 0.800 | 0.750 | 0.418 | 0.393 | 0.025 |

### width=36px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.200 | 0.000 | 0.405 | 0.449 | -0.044 |
| lanczos_x2 | 0.400 | 0.000 | 0.344 | 0.396 | -0.052 |
| lanczos_x4 | 0.200 | 0.000 | 0.340 | 0.407 | -0.067 |

### width=40px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.651 | 0.295 | 0.356 |
| lanczos_x2 | 1.000 | 1.000 | 0.651 | 0.290 | 0.360 |
| lanczos_x4 | 1.000 | 1.000 | 0.651 | 0.288 | 0.363 |

### width=40px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 0.400 | 0.460 | 0.464 | -0.003 |
| lanczos_x2 | 1.000 | 0.800 | 0.437 | 0.378 | 0.059 |
| lanczos_x4 | 1.000 | 0.800 | 0.424 | 0.376 | 0.048 |

### width=40px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.627 | 0.287 | 0.340 |
| lanczos_x2 | 1.000 | 1.000 | 0.609 | 0.294 | 0.315 |
| lanczos_x4 | 1.000 | 1.000 | 0.614 | 0.290 | 0.324 |

### width=40px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.800 | 0.750 | 0.422 | 0.377 | 0.045 |
| lanczos_x2 | 0.800 | 0.750 | 0.449 | 0.383 | 0.066 |
| lanczos_x4 | 0.800 | 0.750 | 0.437 | 0.374 | 0.063 |

### width=40px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.000 | n/a | n/a | n/a | n/a |
| lanczos_x2 | 0.800 | 0.250 | 0.314 | 0.334 | -0.021 |
| lanczos_x4 | 0.800 | 0.250 | 0.326 | 0.347 | -0.021 |

### width=50px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.661 | 0.297 | 0.364 |
| lanczos_x2 | 1.000 | 1.000 | 0.675 | 0.288 | 0.387 |
| lanczos_x4 | 1.000 | 1.000 | 0.673 | 0.293 | 0.380 |

### width=50px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 0.800 | 0.502 | 0.434 | 0.068 |
| lanczos_x2 | 1.000 | 1.000 | 0.503 | 0.360 | 0.143 |
| lanczos_x4 | 1.000 | 1.000 | 0.501 | 0.358 | 0.143 |

### width=50px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.650 | 0.288 | 0.362 |
| lanczos_x2 | 1.000 | 1.000 | 0.641 | 0.277 | 0.364 |
| lanczos_x4 | 1.000 | 1.000 | 0.632 | 0.273 | 0.360 |

### width=50px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.544 | 0.369 | 0.175 |
| lanczos_x2 | 1.000 | 1.000 | 0.570 | 0.351 | 0.220 |
| lanczos_x4 | 1.000 | 1.000 | 0.562 | 0.346 | 0.216 |

### width=50px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 0.600 | 0.333 | 0.375 | 0.382 | -0.007 |
| lanczos_x2 | 1.000 | 0.400 | 0.370 | 0.381 | -0.010 |
| lanczos_x4 | 1.000 | 0.400 | 0.361 | 0.382 | -0.021 |

### width=60px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.665 | 0.294 | 0.370 |
| lanczos_x2 | 1.000 | 1.000 | 0.676 | 0.293 | 0.383 |
| lanczos_x4 | 1.000 | 1.000 | 0.673 | 0.291 | 0.382 |

### width=60px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.570 | 0.398 | 0.172 |
| lanczos_x2 | 1.000 | 1.000 | 0.561 | 0.330 | 0.230 |
| lanczos_x4 | 1.000 | 1.000 | 0.565 | 0.335 | 0.230 |

### width=60px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.651 | 0.286 | 0.366 |
| lanczos_x2 | 1.000 | 1.000 | 0.643 | 0.276 | 0.367 |
| lanczos_x4 | 1.000 | 1.000 | 0.639 | 0.271 | 0.368 |

### width=60px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.550 | 0.308 | 0.241 |
| lanczos_x2 | 1.000 | 1.000 | 0.575 | 0.319 | 0.256 |
| lanczos_x4 | 1.000 | 1.000 | 0.572 | 0.331 | 0.242 |

### width=60px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 0.600 | 0.399 | 0.345 | 0.053 |
| lanczos_x2 | 1.000 | 0.600 | 0.371 | 0.336 | 0.035 |
| lanczos_x4 | 1.000 | 0.600 | 0.373 | 0.341 | 0.032 |

### width=80px, deg=none (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.667 | 0.292 | 0.375 |
| lanczos_x2 | 1.000 | 1.000 | 0.671 | 0.287 | 0.384 |
| lanczos_x4 | 1.000 | 1.000 | 0.671 | 0.291 | 0.380 |

### width=80px, deg=blur (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.616 | 0.340 | 0.276 |
| lanczos_x2 | 1.000 | 1.000 | 0.600 | 0.288 | 0.313 |
| lanczos_x4 | 1.000 | 1.000 | 0.607 | 0.294 | 0.314 |

### width=80px, deg=dark (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.659 | 0.287 | 0.373 |
| lanczos_x2 | 1.000 | 1.000 | 0.646 | 0.267 | 0.379 |
| lanczos_x4 | 1.000 | 1.000 | 0.654 | 0.274 | 0.380 |

### width=80px, deg=jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.607 | 0.295 | 0.312 |
| lanczos_x2 | 1.000 | 1.000 | 0.617 | 0.310 | 0.307 |
| lanczos_x4 | 1.000 | 1.000 | 0.622 | 0.325 | 0.297 |

### width=80px, deg=blur+jpeg20 (n=5)

| variant | det | top1_ok | best_same | best_wrong | margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| downscaled | 1.000 | 1.000 | 0.538 | 0.376 | 0.162 |
| lanczos_x2 | 1.000 | 1.000 | 0.532 | 0.364 | 0.168 |
| lanczos_x4 | 1.000 | 1.000 | 0.529 | 0.374 | 0.156 |

## Distractors (n=12, undegraded full-size det=4/12)

| deg | variant | n_embedded | wrong_match_rate |
| --- | --- | ---: | ---: |
| none | downscaled | 4/12 | too few to conclude |
| none | lanczos_x2 | 6/12 | 0.167 |
| none | lanczos_x4 | 6/12 | 0.333 |
| blur | downscaled | 0/12 | too few to conclude |
| blur | lanczos_x2 | 0/12 | too few to conclude |
| blur | lanczos_x4 | 0/12 | too few to conclude |
| dark | downscaled | 0/12 | too few to conclude |
| dark | lanczos_x2 | 1/12 | too few to conclude |
| dark | lanczos_x4 | 2/12 | too few to conclude |
| jpeg20 | downscaled | 1/12 | too few to conclude |
| jpeg20 | lanczos_x2 | 0/12 | too few to conclude |
| jpeg20 | lanczos_x4 | 1/12 | too few to conclude |
| blur+jpeg20 | downscaled | 0/12 | too few to conclude |
| blur+jpeg20 | lanczos_x2 | 0/12 | too few to conclude |
| blur+jpeg20 | lanczos_x4 | 0/12 | too few to conclude |

## Failure Examples
- f_154027 | width=24 | deg=dark | lanczos_x2 -> /home/mohit/Strix/data/outputs/eval_failures/fail_1_f_154027_w24_dark_lanczos_x2.jpg
- f_154027 | width=24 | deg=dark | lanczos_x4 -> /home/mohit/Strix/data/outputs/eval_failures/fail_2_f_154027_w24_dark_lanczos_x4.jpg
- f_153013 | width=30 | deg=dark | lanczos_x4 -> /home/mohit/Strix/data/outputs/eval_failures/fail_3_f_153013_w30_dark_lanczos_x4.jpg
