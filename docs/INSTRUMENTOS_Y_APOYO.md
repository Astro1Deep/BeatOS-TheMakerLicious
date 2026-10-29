# Banner original y apoyo a BeatOS

El encabezado centrado sobre el banner muestra BeatOS, The MakerLicious y [universal beatmaker station] como texto real del navegador. Se recupera el banner central blueprint y sus ocho temas, con los fondos originales Patchbay, Cables y Liso. Las láminas oscuras y Bone usan las fuentes existentes de 3840 píxeles; las otras conservan sus originales. «Ampliar banner» permite ver los detalles a mayor tamaño.

No se ha aprobado ninguna restauración generativa: la prueba introdujo controles distintos de las referencias y se descartó. Se preservan los píxeles de los originales. Eso evita introducir nuevos botones, pero no convierte los rótulos borrosos o inexactos que ya contenía el arte en documentación técnica fiable. Para corregirlos sin reconstrucción especulativa hace falta un original editable o un dibujo técnico auténtico. Las fotografías se conservan sólo como referencia documental, fuera del banner.

## Apoyo voluntario

Hay una sola entrada «Apoyar BeatOS» en la aplicación, con las plataformas ya enlazadas por el proyecto:

- [Ko-fi / Astro1Deep](https://ko-fi.com/astro1deep): el precio de la unidad es configurable en **Settings → Payment**. La [ayuda oficial](https://help.ko-fi.com/hc/en-us/articles/115004001194-What-if-I-don-t-like-coffee) incluye el caso de una unidad de 1 €. No hay evidencia de un mínimo universal de 5 €. El formulario público de Astro1Deep se verificó en navegador: moneda USD, campo con mínimo 5 y mensaje «Please enter at least $5» al escribir 1. Para ofrecer 1 € hay que ajustar la moneda y el mínimo en esa cuenta y volver a comprobarlo; BeatOS no cambia la configuración financiera.
- [GitHub Sponsors / Astro1Deep](https://github.com/sponsors/Astro1Deep): el perfil público existe y muestra importes personalizados, sin mínimo personalizado declarado en el HTML examinado. [GitHub permite configurar un mínimo](https://docs.github.com/en/sponsors/receiving-sponsorships-through-github-sponsors/managing-your-sponsorship-tiers); sus niveles se expresan en **USD**, por lo que 1 USD no equivale necesariamente a 1 EUR. No se realizó ningún pago para probar la aceptación final.
- El README también enlazaba PayPal.Me/Astro1Deep. La URL respondió con una página genérica «Obtén tu propio vínculo de PayPal.Me», sin acreditar el destinatario. Se conserva como antecedente en esta auditoría y no se añade al menú de cobro hasta verificar el perfil y el importe.

El menú no promete «1 €» mientras el cobro real no esté acreditado. No se crearon cuentas ni se modificaron mínimos, suscripciones o medios de pago.

## Mutes y formatos

Por defecto: bombo 1, hi-hat 2, caja 3 y resto 0 (libre). Los ajustes explícitos del usuario, incluido 0, se respetan al importar y exportar kits nuevos. El editor permite otros grupos. Un mismo grupo positivo se corta entre sí; grupos distintos pueden sonar a la vez.

MPC XPM/XPJ guarda grupos nativos. Maschine se entrega como WAV y mapa JSON, no como grupo .mxgrp. EP-133 recibe WAV normalizados, mapa y ZIP de transporte, no un backup nativo del fabricante; sus asignaciones deben trasladarse al equipo. Roland recibe audio ordenado y los grupos se ajustan en el hardware. El reel de PO-33 es audio para muestrear, no transmite metadatos de mute. Las pruebas de archivos no sustituyen una prueba de carga y ejecución en cada equipo físico.

El rack importa y reexporta la primera capa activa por pad. No es un editor completo de programas multicapa; el archivo original conserva todas sus capas.
