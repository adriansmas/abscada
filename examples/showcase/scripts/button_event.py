ctx.state['clicks'] = ctx.state.get('clicks', 0) + 1
ctx.write('Sistema.UltimoEvento', 'Script de botón: ejecución ' + str(ctx.state['clicks']))
print('Botón en pantalla', ctx.screen)
