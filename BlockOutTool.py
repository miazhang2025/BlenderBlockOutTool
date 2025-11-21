bl_info = {
    "name": "Block Out Tool",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Block Out",
    "description": "Place block cubes and swap them with assets",
    "category": "3D View",
}

import bpy
import os
from bpy.props import StringProperty, EnumProperty, BoolProperty, FloatVectorProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector
import glob


class BlockOutProperties(PropertyGroup):
    """Properties for the block out tool"""
    
    asset_folder: StringProperty(
        name="Asset Folder",
        description="Folder containing 3D assets (FBX, OBJ, etc.)",
        default="",
        subtype='DIR_PATH'
    )
    
    block_size: FloatVectorProperty(
        name="Block Size",
        description="Size of block cubes to place",
        default=(2.0, 2.0, 2.0),
        min=0.1,
        soft_max=10.0,
        subtype='XYZ'
    )
    
    use_cursor: BoolProperty(
        name="Place at Cursor",
        description="Place blocks at 3D cursor location",
        default=True
    )
    
    keep_transform: BoolProperty(
        name="Keep Transform",
        description="Keep position, rotation, and scale when swapping",
        default=True
    )
    
    link_or_append: EnumProperty(
        name="Import Method",
        description="Link or append assets",
        items=[
            ('APPEND', "Append", "Append assets (makes them local)"),
            ('LINK', "Link", "Link assets (keeps them external)"),
        ],
        default='APPEND'
    )


class BLOCKOUT_OT_place_cube(Operator):
    """Place a block cube in the scene"""
    bl_idname = "blockout.place_cube"
    bl_label = "Place Block Cube"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.blockout_props
        
        # Create a cube
        bpy.ops.mesh.primitive_cube_add()
        cube = context.active_object
        
        # Set size
        cube.scale = props.block_size
        
        # Position at cursor if enabled
        if props.use_cursor:
            cube.location = context.scene.cursor.location.copy()
        
        # Name it as a block
        cube.name = "Block_Cube"
        
        # Add custom property to identify as blockout object
        cube["is_blockout"] = True
        
        # Optional: Add a material to distinguish blockout objects
        if "BlockOut_Material" not in bpy.data.materials:
            mat = bpy.data.materials.new(name="BlockOut_Material")
            mat.use_nodes = True
            mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.3, 0.5, 0.8, 0.5)
            mat.blend_method = 'BLEND'
        else:
            mat = bpy.data.materials["BlockOut_Material"]
        
        if cube.data.materials:
            cube.data.materials[0] = mat
        else:
            cube.data.materials.append(mat)
        
        return {'FINISHED'}


class BLOCKOUT_OT_swap_with_asset(Operator):
    """Swap selected block cubes with an asset"""
    bl_idname = "blockout.swap_with_asset"
    bl_label = "Swap with Asset"
    bl_options = {'REGISTER', 'UNDO'}
    
    asset_path: StringProperty()
    
    def execute(self, context):
        props = context.scene.blockout_props
        
        if not self.asset_path or not os.path.exists(self.asset_path):
            self.report({'ERROR'}, "Invalid asset path")
            return {'CANCELLED'}
        
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_objects:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        # Reset error tracking
        self.import_errors = []
        
        # Import the asset
        imported_objects = self.import_asset(self.asset_path, props.link_or_append)
        
        if not imported_objects:
            filename = os.path.basename(self.asset_path)
            if self.import_errors:
                self.report({'ERROR'}, self.import_errors[0])
            else:
                self.report({'ERROR'}, f"Failed to import {filename}")
            return {'CANCELLED'}
        
        # Get the root object(s) from import
        root_objects = [obj for obj in imported_objects if obj.parent is None]
        
        # Swap each selected object
        replaced_count = 0
        for block in selected_objects:
            # Store transform
            location = block.location.copy()
            rotation = block.rotation_euler.copy()
            scale = block.scale.copy()
            
            # Duplicate the imported asset
            new_objects = []
            for root in root_objects:
                new_root = self.duplicate_hierarchy(root)
                new_objects.append(new_root)
                
                if props.keep_transform:
                    new_root.location = location
                    new_root.rotation_euler = rotation
                    new_root.scale = scale
            
            # Delete the block cube
            bpy.data.objects.remove(block, do_unlink=True)
            replaced_count += 1
        
        # Delete the original imported objects
        for obj in imported_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        
        self.report({'INFO'}, f"Replaced {replaced_count} object(s) with {os.path.basename(self.asset_path)}")
        return {'FINISHED'}
    
    def import_asset(self, filepath, method):
        """Import an asset file (FBX, OBJ, etc.)"""
        ext = os.path.splitext(filepath)[1].lower()
        filename = os.path.basename(filepath)
        
        # Store objects before import
        objects_before = set(bpy.data.objects)
        
        try:
            if ext == '.fbx':
                bpy.ops.import_scene.fbx(filepath=filepath)
            elif ext == '.obj':
                bpy.ops.import_scene.obj(filepath=filepath)
            elif ext in ['.gltf', '.glb']:
                bpy.ops.import_scene.gltf(filepath=filepath)
            elif ext == '.dae':
                bpy.ops.wm.collada_import(filepath=filepath)
            elif ext in ['.stl']:
                bpy.ops.import_mesh.stl(filepath=filepath)
            elif ext == '.ply':
                bpy.ops.import_mesh.ply(filepath=filepath)
            elif ext == '.blend':
                # For .blend files, append/link objects
                with bpy.data.libraries.load(filepath, link=(method == 'LINK')) as (data_from, data_to):
                    data_to.objects = data_from.objects
                
                # Link to scene
                imported = []
                for obj in data_to.objects:
                    if obj is not None:
                        bpy.context.collection.objects.link(obj)
                        imported.append(obj)
                return imported
            else:
                return []
            
            # Get newly imported objects
            objects_after = set(bpy.data.objects)
            imported_objects = list(objects_after - objects_before)
            
            return imported_objects
            
        except RuntimeError as e:
            error_msg = str(e)
            # Check for specific FBX version error
            if "Version" in error_msg and "unsupported" in error_msg:
                print(f"FBX Version Error for {filename}: {error_msg}")
                print(f"This FBX file uses an older format. Consider converting it to FBX 7.1 or later.")
                # Store error for reporting
                if not hasattr(self, 'import_errors'):
                    self.import_errors = []
                self.import_errors.append(f"{filename}: Unsupported FBX version (too old)")
            else:
                print(f"Error importing {filepath}: {e}")
                if not hasattr(self, 'import_errors'):
                    self.import_errors = []
                self.import_errors.append(f"{filename}: {str(e)[:100]}")
            return []
        except Exception as e:
            print(f"Error importing {filepath}: {e}")
            if not hasattr(self, 'import_errors'):
                self.import_errors = []
            self.import_errors.append(f"{filename}: {str(e)[:100]}")
            return []
    
    def duplicate_hierarchy(self, obj):
        """Duplicate an object and its children"""
        # Duplicate the object
        new_obj = obj.copy()
        if obj.data:
            new_obj.data = obj.data.copy()
        
        bpy.context.collection.objects.link(new_obj)
        
        # Duplicate children recursively
        for child in obj.children:
            new_child = self.duplicate_hierarchy(child)
            new_child.parent = new_obj
        
        return new_obj


class BLOCKOUT_OT_refresh_assets(Operator):
    """Refresh the asset list"""
    bl_idname = "blockout.refresh_assets"
    bl_label = "Refresh Assets"
    
    def execute(self, context):
        # This will trigger a redraw and re-scan the folder
        context.area.tag_redraw()
        return {'FINISHED'}


class BLOCKOUT_PT_main_panel(Panel):
    """Main panel for block out tool"""
    bl_label = "Block Out Tool"
    bl_idname = "BLOCKOUT_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Block Out'
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.blockout_props
        
        # Block Placement Section
        box = layout.box()
        box.label(text="Place Blocks", icon='MESH_CUBE')
        box.prop(props, "block_size")
        box.prop(props, "use_cursor")
        box.operator("blockout.place_cube", icon='ADD')
        
        # Asset Swapping Section
        box = layout.box()
        box.label(text="Swap with Assets", icon='FILE_FOLDER')
        box.prop(props, "asset_folder")
        
        row = box.row()
        row.operator("blockout.refresh_assets", icon='FILE_REFRESH')
        
        box.prop(props, "keep_transform")
        box.prop(props, "link_or_append")
        
        # List available assets
        if props.asset_folder and os.path.isdir(props.asset_folder):
            box.label(text="Available Assets:", icon='ASSET_MANAGER')
            
            # Supported formats
            extensions = ['*.fbx', '*.obj', '*.gltf', '*.glb', '*.dae', '*.stl', '*.ply', '*.blend']
            assets = []
            
            for ext in extensions:
                assets.extend(glob.glob(os.path.join(props.asset_folder, ext)))
                # Also check subdirectories
                assets.extend(glob.glob(os.path.join(props.asset_folder, '**', ext), recursive=True))
            
            assets = sorted(set(assets))
            
            if assets:
                # Create a scrollable list
                col = box.column(align=True)
                for asset_path in assets[:20]:  # Limit display to 20 items
                    asset_name = os.path.basename(asset_path)
                    op = col.operator("blockout.swap_with_asset", text=asset_name, icon='OBJECT_DATA')
                    op.asset_path = asset_path
                
                if len(assets) > 20:
                    col.label(text=f"... and {len(assets) - 20} more", icon='INFO')
            else:
                box.label(text="No assets found", icon='ERROR')
        else:
            box.label(text="Select a valid folder", icon='INFO')


# Registration
classes = (
    BlockOutProperties,
    BLOCKOUT_OT_place_cube,
    BLOCKOUT_OT_swap_with_asset,
    BLOCKOUT_OT_refresh_assets,
    BLOCKOUT_PT_main_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.blockout_props = bpy.props.PointerProperty(type=BlockOutProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    del bpy.types.Scene.blockout_props


if __name__ == "__main__":
    register()