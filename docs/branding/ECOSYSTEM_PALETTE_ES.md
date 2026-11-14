# Astro1Deep — Paleta & tema del ecosistema

![Banner Astro1Deep](../assets/branding/creator/astro1deep-banner.png)

**Dirección visual:** *obsidiana cromada*: la sobriedad oscura y el emblema metálico del banner, traducidos a una interfaz clara, legible y funcional. El cromado es un acento, no el color de todo el texto.

## Paleta base

| Token | Color | Uso |
|---|---|---|
| `void` | `#090A0C` | Fondo profundo; portada, hero y zonas de descanso visual. |
| `canvas` | `#101216` | Fondo principal de páginas y aplicaciones. |
| `surface` | `#171B20` | Tarjetas, paneles y navegación. |
| `raised` | `#20252B` | Elementos elevados, campos y superficies seleccionadas. |
| `line` | `#3C444E` | Bordes, separadores y contornos no interactivos. |
| `text` | `#F2F4F7` | Texto principal, títulos y controles importantes. |
| `text-muted` | `#B8C0CA` | Texto secundario, metadatos y descripciones. |
| `chrome` | `#C7D1DC` | Acento metálico: iconos, enlaces, selección y marca. |
| `focus` | `#AFC2D4` | Anillo de foco y estados interactivos accesibles. |

## Colores de estado

| Estado | Color | Aplicación |
|---|---|---|
| Correcto | `#8ED8B3` | Confirmación y operación completada. |
| Atención | `#E9C879` | Avisos, cambios pendientes y cautela. |
| Error | `#FF858C` | Errores y acciones destructivas; nunca como único indicador. |
| Información | `#AFC2D4` | Ayuda, datos y notificaciones neutrales. |

Los estados se acompañan de texto o iconos con significado; el color nunca es la única señal.

## Contraste verificado

Ratios calculados según la fórmula de luminancia relativa WCAG. Todas las combinaciones de texto listadas superan **7:1**, por encima del mínimo de **4.5:1** para texto normal.

| Primer plano / fondo | Contraste |
|---|---:|
| `text` sobre `void` | 17.97:1 |
| `text-muted` sobre `void` | 10.78:1 |
| `chrome` sobre `surface` | 11.19:1 |
| `focus` sobre `void` | 10.84:1 |
| `success` sobre `void` | 11.91:1 |
| `warning` sobre `void` | 12.26:1 |
| `error` sobre `void` | 8.47:1 |
| `void` sobre botón `chrome` | 12.81:1 |

## Tokens CSS

```css
:root {
  color-scheme: dark;
  --atd-void: #090a0c;
  --atd-canvas: #101216;
  --atd-surface: #171b20;
  --atd-raised: #20252b;
  --atd-line: #3c444e;
  --atd-text: #f2f4f7;
  --atd-text-muted: #b8c0ca;
  --atd-chrome: #c7d1dc;
  --atd-focus: #afc2d4;
  --atd-success: #8ed8b3;
  --atd-warning: #e9c879;
  --atd-danger: #ff858c;
  --atd-info: #afc2d4;
}

body {
  background: var(--atd-canvas);
  color: var(--atd-text);
}

:focus-visible {
  outline: 2px solid var(--atd-focus);
  outline-offset: 3px;
}

.button-primary {
  color: var(--atd-void);
  background: var(--atd-chrome);
}
```

## Reglas de uso

- **Marca:** conservar el emblema cromado sobre `void` o `canvas`; reservar el brillo y los reflejos para el logo y piezas de portada.
- **Legibilidad:** usar `text` y `text-muted` para lectura. No usar gris metálico oscuro como texto ni simular el acabado cromado en párrafos.
- **Jerarquía:** alternar `canvas`, `surface` y `raised` para separar áreas; bordes discretos, espaciado generoso y pocas sombras.
- **Acento:** aplicar `chrome` a enlaces, selección y acciones primarias, no a todas las superficies a la vez. Texto oscuro sobre botones `chrome`.
- **Interacción:** mantener foco visible de teclado, estados hover/pressed diferenciados y estados de error/éxito con icono o etiqueta además del color.
- **GitHub:** usar `void` para banner o bloque de marca; en README mantener el cuerpo sobre fondo normal y añadir el acento metálico en encabezados, enlaces e insignias. Evitar convertir todo el README en una gran superficie negra.
- **Impresión y modo claro:** esta propuesta define el tema oscuro del ecosistema; los documentos deben seguir siendo comprensibles si GitHub los muestra con un tema claro, sin depender de fondos o imágenes para transmitir información.

**Resultado:** una identidad lúgubre, monocroma y metálica, con una capa de interfaz separada que conserva contraste y claridad.
