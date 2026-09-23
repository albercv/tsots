"""Publicación en redes sociales (TikTok, YouTube, Instagram).

El paquete es independiente del proveedor: la app solo usa los tipos neutros
de `modelo`, los límites de `textos`, el protocolo `proveedor.Proveedor`, el
orquestador `publicador` y el registro local `registro`. Todo lo propio de un
servicio concreto vive en su módulo (hoy, uno solo) y se elige por nombre en
`proveedor.PROVEEDORES`.
"""
