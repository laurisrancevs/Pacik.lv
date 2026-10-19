# PACIK.LV production smoke tests

After Cloud Run deploy, run these public API checks:

1. /valuation?q=Purvciema%20iela%2020&area=50&city=Rīga
   - HTTP 200
   - selection_method = hierarchical_geo_similarity_v3
   - estimated_value > 0
   - comparable_count > 0
   - target_coordinates present

2. /valuation?q=Raņķa%20dambis%205&area=60&city=Rīga
   - HTTP 200
   - residential target building
   - estimated_value > 0
   - comparable_count > 0

3. /valuation?q=Purvciema%20iela%2038&area=50&city=Rīga
   - HTTP 422
   - code = building_type_mismatch

These are regression checks for valuation, geographic matching, and the non-residential safety guard.
