-- Test: does the frame callback fire multiple times?
local count = 0
local cb = callbacks:add("frame", function()
  count = count + 1
  if count <= 5 or count % 30 == 0 then
    local f = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_frame_count.txt", "w")
    if f then f:write("frames=" .. count .. "\n"); f:close() end
  end
  if count >= 120 then
    cb:remove()
    local f = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_frame_count.txt", "w")
    if f then f:write("DONE frames=" .. count .. "\n"); f:close() end
  end
end)
