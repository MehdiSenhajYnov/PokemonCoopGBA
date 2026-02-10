# Launch the TCP relay server (output to server_log.txt)
node "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\server\server.js" 2>&1 | Tee-Object -FilePath "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\server_log.txt"
