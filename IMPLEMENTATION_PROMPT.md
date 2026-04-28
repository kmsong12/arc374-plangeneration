# ARC374 Floor Plan Generator - UI Improvements Implementation Prompt

## Overview
Implement 5-6 feature improvements for the custom furniture editor and room authoring interface. Focus on UI consistency, proper scaling, enhanced placement constraints, deletion capability, and improved navigation.

---

## Feature 1: Fix Custom Furniture Editor Scale (CRITICAL FIX)

### Current Issue
The CustomFurnitureEditor (stages/stage_author.py::class CustomFurnitureEditor) has a canvas that is scaled up 3x (BASE_W * 3, BASE_H * 3) with a 3x zoom applied during drawing. This causes the furniture library to be dragged out of scale, making primitives appear much larger than actual size when placed in rooms.

### Requirements
1. **Examine the current scaling**:
   - Canvas size: `BASE_W * 3, BASE_H * 3` 
   - Drawing scaling factor: `3` in `_draw_primitive()` calls
   - This 3x scaling is NOT reflected in the final CustomFurniture that gets stored

2. **Fix the scale representation**:
   - Reduce canvas to actual size (BASE_W × BASE_H, no 3x multiplier)
   - Remove the `3` scale factor from all `_draw_primitive()` calls in _redraw()
   - Update `_world()` method to not divide by 3 (just return cx, cy directly or with proper grid snapping)
   - Ensure primitives drawn in the editor match 1:1 with how they render when placed in rooms

3. **Preserve interaction**:
   - Keep all drag/drop, selection, and drawing mechanics intact
   - Ensure hit-testing still works correctly
   - Selection preview (orange outline) should still display properly

---

## Feature 2: Update Custom Furniture Editor UI to Match Room Template Library

### Current State Reference
Look at `_build_left_sidebar()` and how it renders the standard furniture catalog tiles - these show proper visual hierarchy and information layout.

### Requirements
1. **Apply consistent styling to CustomFurnitureEditor**:
   - Use the same color scheme from theme.py (C["panel"], C["accent"], etc.)
   - Add proper section headers and instructional text
   - Match button styling with label_button() helper function

2. **Improve the tool selection UI**:
   - Current: horizontal radiobuttons (rect, square, circle, triangle, line)
   - Better: organized grid with icons or better labeling
   - Add hover tooltips explaining each shape type
   - Consider visual distinction for active tool

3. **Add a primitives list view** (similar to library view):
   - Show all primitives in the furniture with index, type, dimensions
   - Highlight selected primitive in the list
   - Allow right-click context menu (delete, duplicate, modify)
   - Show bounding box and color swatch for each

4. **Improve the canvas area**:
   - Add canvas size label: "Base: XXinch × XXinch" or in feet
   - Add grid lines or gridlines toggle
   - Display ruler or dimension guides along axes
   - Add "Fit to canvas" button if drawing goes outside bounds

5. **Reorganize the dialog**:
   - Group controls logically (Title | Tool Selection | Canvas | Primitives List | Buttons)
   - Add clear section separators
   - Make the dialog more spacious with proper padding (padx=10, pady similar to other dialogs)

---

## Feature 3: Constrain Windows & Doors to Room Edges Only

### Current Behavior
Windows and doors can be placed anywhere on the canvas; they should only snap to and place on room polygon edges.

### Requirements
1. **Identify edge-snap types**:
   - Search for `_EDGE_SNAP_TYPES` in stage_author.py (should include 'window' and 'door')

2. **Implement edge-only placement**:
   - When armed furniture is a window or door, on canvas click:
     - Find nearest room polygon edge
     - Calculate closest point on that edge to the mouse click
     - ONLY allow placement if the furniture can fit fully on that edge (parallel and overlapping)
   - If edge placement is invalid or edge too short, show error in status bar

3. **Visual feedback during placement**:
   - While hovering with window/door armed, highlight the nearest edge in a bright color
   - Show preview of placement snapped to that edge
   - Display error (red highlight) if placement would be invalid

4. **Validation for placement**:
   - Ensure furniture width/length overlaps significantly with the edge (not just touching endpoints)
   - Ensure furniture stays within the room bounds
   - Furniture center should lie ON the edge line (parallel constraint)

---

## Feature 4: Fix Door Arc Orientation

### Current Issue
Doors have an arc that currently appears on the short width side; it should appear on the long length side (the swing direction).

### References
- Search for door-related drawing in canvas_renderer.py or furniture rendering code
- Look for arc drawing using canvas.create_arc()

### Requirements
1. **Locate door rendering code**:
   - Find where door arc is drawn (likely in RoomCanvasRenderer or furniture drawing function)
   - Door should have the arc on the long edge (length dimension), not width

2. **Fix the arc orientation**:
   - If door width is W and height is H, and the door is placed on a horizontal edge:
     - Arc should extend along the H dimension (vertical swing arc)
   - If on a vertical edge:
     - Arc should extend along the W dimension (horizontal swing arc)
   - Current code likely has this reversed

3. **Test**:
   - Place a door horizontally on a wall
   - Verify arc swings along the door's length (long side)
   - Place a door vertically and verify same behavior

---

## Feature 5: Delete Selected Furniture from Rooms

### Current State
- `_delete_selection()` exists in AuthorStage but only handles rooms being authored
- Need to add delete capability when viewing room templates in the sidebar

### Requirements
1. **In the room library sidebar** (when viewing a template):
   - When a user clicks on a room template in the right sidebar to view it
   - Show furniture items in that template
   - Add a UI affordance (trash icon, delete button, or right-click context menu)
   - Clicking delete removes that furniture piece from the template

2. **Implementation approach**:
   - Modify `_render_library()` to show furniture items for each room template
   - Add a "delete" button next to each furniture item in the preview
   - When clicked: remove from template.furniture[], redraw, push undo

3. **UX consideration**:
   - Make delete non-destructive with undo (use _push_undo())
   - Update status bar to show "Deleted furniture from [room name]"
   - Only enable delete if at least one furniture piece is selected or visible

---

## Feature 6: Add "Home" Button to Navigate Back After Viewing Room in Sidebar

### Current Problem
When viewing a room template from the sidebar (by clicking it), the user cannot navigate back to the room they were actively editing. The "Back to previous" button is for template stack navigation, not for returning to active editing.

### Requirements
1. **Add a "Home" or "Return to Editing" button**:
   - Location: Add to the right sidebar, near "Back to previous" button
   - Label: "🏠 Home" or "← Return to Editing" or similar
   - Only show if the user has an active template being edited (self._editing_key is set)

2. **Behavior**:
   - Clicking the home button should:
     - Clear the template stack (self._template_stack.clear())
     - Restore self._new_blank_template() if no editing was active, OR
     - Restore the last actively-edited room back to the canvas
   - Save the current room state before switching (optional but recommended)

3. **Implementation**:
   - Store the "active editing" template separately: `self._active_editing_template`
   - When user clicks a room from library, save current to stack
   - When user clicks "Home", pop from stack and restore
   - Update UI: `_sync_back_button()` should also show/hide Home button appropriately

4. **Button placement in nav2 frame** (stages/stage_author.py around line 448):
   ```python
   nav2 = tk.Frame(top, bg=C["panel"]); nav2.pack(fill="x", pady=(0, 2))
   label_button(nav2, "+ New room template", self._new_room_from_sidebar, primary=True)
   self._home_btn = label_button(nav2, "🏠 Home", self._return_to_active_editing)
   self._home_btn.pack(side="left", padx=(0, 4))
   self._sync_home_button()  # Add new method to show/hide
   ```

---

## Implementation Notes

### File Locations to Modify
- **stages/stage_author.py**: CustomFurnitureEditor class, AuthorStage navigation
- **canvas_renderer.py**: Door/window rendering and arc orientation
- **model/custom_furniture.py**: CustomFurniture and Primitive classes (as needed)
- **theme.py**: If adding new UI components (unlikely, use existing colors)

### Testing Checklist
- [ ] Custom furniture primitives display at 1:1 scale matching room placement
- [ ] Custom furniture editor UI is visually consistent with library
- [ ] Windows and doors can ONLY be placed on edges, not floating
- [ ] Door arc swings along the long dimension
- [ ] Furniture can be deleted from room templates via sidebar
- [ ] Home button appears only when editing and successfully restores editing state

### Undo/Redo Integration
- All changes to template.furniture should call `_push_undo()` first
- Changes propagate through `_redraw()` to update canvas
- Status bar updates with `self.shell.set_status(message)`

---

## Summary: 5-6 Features to Implement
1. ✅ Fix CustomFurnitureEditor scale (3x to 1x)
2. ✅ Update CustomFurnitureEditor UI to match furniture template library styling
3. ✅ Constrain windows/doors to room edges only (parallel + overlapping)
4. ✅ Fix door arc to appear on long length side
5. ✅ Add delete option for furniture in room templates
6. ✅ Add "Home" button to return to active editing from sidebar

All changes should maintain existing undo/redo functionality and visual consistency with the current theme.
