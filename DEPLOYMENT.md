# Deploy / CD

Los manifiestos Kubernetes de esta app **NO viven en este repo**: están en
[`k8s-sied-ar`](https://github.com/siedgustavo/k8s-sied-ar) bajo
`deployments/routerstats/k8s`. El CD se maneja con **ArgoCD**
(Application `routerstats`, autosync + selfHeal, alta automática vía la
ApplicationSet `deployments`).

Este repo contiene solo el código y el build/push de la imagen:

```bash
./build-and-push.sh [tag]   # default: latest
```

Requiere estar logueado (`docker login ghcr.io`) con un token con permiso
`write:packages` — el script no embebe ningún credential.

## Qué corre en el cluster

- `CronJob router-reconciler` (namespace `routerstats`, cada 5 minutos) —
  compara el estado real del router contra el deseado (WiFi apagado,
  reserva DHCP del Mikrotik, DMZ) y reaplica si detecta drift (típicamente
  después de que la OLT del ISP pisa la config en un reboot).
- Las credenciales del router viven en el Secret `router-credentials`
  (`user`/`pass`), sellado con kubeseal en el repo de manifiestos — ver
  `core/sealed-secrets/README.md` de `k8s-sied-ar` para cambiarlas.
