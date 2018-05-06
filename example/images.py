import elphie

images = elphie.Images(100, 100)

img = images.new_image("a1")
code = img.code("""#include <stdio.h>
/* Hello world program */

int main() {
    printf("Hello world!\\n");
    return 0;
}""", "c")

img = images.new_image("a2", width=30, preferDrawingSize=False)

images.render()
