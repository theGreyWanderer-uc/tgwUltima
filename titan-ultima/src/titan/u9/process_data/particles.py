"""Particle process presets, forces, generations and instances."""

from __future__ import annotations

__all__ = [
    "U9ParticleItemVariantState",
    "U9ParticleCameraFilterTextureState",
    "U9ParticleRampSlotState",
    "U9ParticlePresetState",
    "U9ParticleForcePresetState",
    "U9ParticleForceState",
    "U9ParticleGenerationState",
    "U9ParticleInstanceState",
    "U9ParticleRecordCollection",
    "U9ParticleRecordCollections",
    "U9ParticleProcessState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import U9ProcessDataError, _require_bytes


PARTICLE_PROCESS_VERSIONS = frozenset({3, 5})
PARTICLE_PROCESS_STATE_SIZE = 33
PARTICLE_PRESET_RECORD_SIZES = {3: 1484, 5: 1490}
PARTICLE_FORCE_PRESET_RECORD_SIZE = 97
PARTICLE_FORCE_RECORD_SIZE = 24
PARTICLE_GENERATION_RECORD_SIZE = 124
PARTICLE_INSTANCE_RECORD_SIZE = 196
PARTICLE_FORCE_PRESET_RECORD = struct.Struct("<iBiii3ffii3fi3f3fiiii")
PARTICLE_FORCE_RECORD = struct.Struct("<ii3fi")
PARTICLE_GENERATION_RECORD = struct.Struct("<31i")
PARTICLE_INSTANCE_RECORD = struct.Struct("<3i10i2i3f3f3f3f4f4f2iBHI4iIB5i")
PARTICLE_CAMERA_FILTER_TEXTURE_RECORD = struct.Struct("<4H8BI")
PARTICLE_RAMP_SLOT_RECORD = struct.Struct("<4i3fi3fiBiBi3i3Bi4i3Bi2i")
PARTICLE_ITEM_VARIANT_COUNT = 10
PARTICLE_RAMP_SLOT_COUNT = 10
PARTICLE_PRESET_VERSION_5_ITEM_EXTENSION_SIZE = 2
PARTICLE_PRESET_VERSION_5_RAMP_EXTENSION_SIZE = 4


@dataclass(frozen=True)
class U9ParticleItemVariantState:
    """One object type and frame delay in a particle preset's display list."""

    object_type_id: int
    swap_time_frames: int


@dataclass(frozen=True)
class U9ParticleCameraFilterTextureState:
    """The fixed 20-byte texture state used by a particle camera filter."""

    texture_id: int
    flags: int
    first_face_index: int
    face_count: int
    default_alpha: int
    current_alpha: int
    start_frame: int
    end_frame: int
    current_frame: int
    animation_rate: int
    animation_type: int
    animation_direction: int
    animation_time: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleCameraFilterTextureState:
        _require_bytes(
            data,
            offset,
            PARTICLE_CAMERA_FILTER_TEXTURE_RECORD.size,
            "particle camera-filter texture",
        )
        values = PARTICLE_CAMERA_FILTER_TEXTURE_RECORD.unpack_from(data, offset)
        return cls(
            texture_id=values[0],
            flags=values[1],
            first_face_index=values[2],
            face_count=values[3],
            default_alpha=values[4],
            current_alpha=values[5],
            start_frame=values[6],
            end_frame=values[7],
            current_frame=values[8],
            animation_rate=values[9],
            animation_type=values[10],
            animation_direction=values[11],
            animation_time=values[12],
        )


@dataclass(frozen=True)
class U9ParticleRampSlotState:
    """One aligned key slot shared by all particle-preset ramp tracks."""

    spawn_mean_value: int
    spawn_mean_frame: int
    lifetime_value: int
    lifetime_frame: int
    object_scale: tuple[float, float, float]
    object_scale_frame: int
    object_color: tuple[float, float, float]
    object_color_frame: int
    object_translucency: int
    object_translucency_frame: int
    object_luminance: int
    object_luminance_frame: int
    skeletal_animation_id: int
    skeletal_blend_duration: int
    skeletal_animation_frame: int
    light_color: tuple[int, int, int]
    light_color_frame: int
    light_range: int
    light_range_frame: int
    light_diffusion: int
    light_diffusion_frame: int
    camera_filter_color: tuple[int, int, int]
    camera_filter_color_frame: int
    camera_filter_translucency: int
    camera_filter_translucency_frame: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleRampSlotState:
        _require_bytes(
            data,
            offset,
            PARTICLE_RAMP_SLOT_RECORD.size,
            "particle ramp slot",
        )
        values = PARTICLE_RAMP_SLOT_RECORD.unpack_from(data, offset)
        return cls(
            spawn_mean_value=values[0],
            spawn_mean_frame=values[1],
            lifetime_value=values[2],
            lifetime_frame=values[3],
            object_scale=tuple(values[4:7]),
            object_scale_frame=values[7],
            object_color=tuple(values[8:11]),
            object_color_frame=values[11],
            object_translucency=values[12],
            object_translucency_frame=values[13],
            object_luminance=values[14],
            object_luminance_frame=values[15],
            skeletal_animation_id=values[16],
            skeletal_blend_duration=values[17],
            skeletal_animation_frame=values[18],
            light_color=tuple(values[19:22]),
            light_color_frame=values[22],
            light_range=values[23],
            light_range_frame=values[24],
            light_diffusion=values[25],
            light_diffusion_frame=values[26],
            camera_filter_color=tuple(values[27:30]),
            camera_filter_color_frame=values[30],
            camera_filter_translucency=values[31],
            camera_filter_translucency_frame=values[32],
        )


@dataclass(frozen=True)
class U9ParticlePresetState:
    """One complete versioned particle appearance and behavior preset."""

    version: int
    record_id: int
    particle_id: int
    critical_flag: int
    lifetime: int
    lifetime_variation: int
    initial_age: int
    spawn_shape: int
    use_transforms_flag: int
    location: tuple[float, float, float]
    offset_vector: tuple[float, float, float]
    location_inherit_flag: int
    location_slave_flag: int
    linear_maximum: tuple[float, float, float]
    minimum_radius: float
    maximum_radius: float
    scale: tuple[float, float, float]
    uniform_scale_variation: float
    scale_distortion_variation: tuple[float, float, float]
    scale_inherit_flag: int
    scale_slave_flag: int
    linear_speed: tuple[float, float, float]
    radial_speed: float
    speed_variation: float
    speed_inherit_flag: int
    minimum_angle: int
    maximum_angle: int
    use_orientation_flag: int
    orientation_quaternion: tuple[float, float, float, float]
    orientation_variation_quaternion: tuple[float, float, float, float]
    orientation_inherit_flag: int
    orientation_slave_flag: int
    rotation_quaternion: tuple[float, float, float, float]
    rotation_variation_quaternion: tuple[float, float, float, float]
    rotation_inherit_flag: int
    spawn_mean_birth: int
    spawn_mean_lifetime: int
    spawn_pulse_flag: int
    spawn_pulse_on_frames: int
    spawn_pulse_off_frames: int
    spawn_mean_death: int
    distribute_spawn_flag: int
    use_assigned_object_flag: int
    appearance_inherit_flag: int
    object_type_count: int
    swap_enabled_flag: int
    random_selection_flag: int
    sequence_index: int
    solid_flag: int
    ignore_collisions_flag: int
    no_kill_flag: int
    object_color: tuple[int, int, int]
    object_translucency: int
    object_luminance: int
    version_5_item_extension: bytes
    camera_space_flag: int
    item_variants: tuple[U9ParticleItemVariantState, ...]
    use_light_flag: int
    light_color: tuple[int, int, int]
    light_diffusion: int
    light_range: int
    negative_light_flag: int
    overbright_light_flag: int
    sound_template_id: int
    sound_category_id: int
    global_sound_flag: int
    loop_sound_flag: int
    link_number: int
    camera_shock_build: float
    camera_shock_decay: float
    camera_shock_intensity: int
    calculate_ramps_by_lifespan_flag: int
    spawn_mean_ramp_count: int
    lifespan_keyframes: int
    object_scale_ramp_count: int
    object_color_ramp_count: int
    object_translucency_ramp_count: int
    object_luminance_ramp_count: int
    skeletal_animation_count: int
    random_skeletal_animation_flag: int
    light_color_keyframes: int
    light_range_keyframes: int
    light_diffusion_keyframes: int
    camera_filter_layer: int
    camera_filter_texture: U9ParticleCameraFilterTextureState
    camera_filter_edge_color: tuple[int, int, int]
    camera_filter_center_color: tuple[int, int, int]
    camera_filter_additive_flag: int
    camera_filter_color_ramp_count: int
    camera_filter_translucency_ramp_count: int
    version_5_ramp_extension: bytes
    ramp_slots: tuple[U9ParticleRampSlotState, ...]
    use_parent_skeleton_flag: int
    skeleton_appearance_id: int
    skeleton_limb_id: int
    skeleton_attachment_id: int
    source_object_reference_index: int
    skeleton_object_reference_index: int
    offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, version: int
    ) -> U9ParticlePresetState:
        if version not in PARTICLE_PRESET_RECORD_SIZES:
            raise U9ProcessDataError(f"unsupported particle-preset version {version}")
        record_size = PARTICLE_PRESET_RECORD_SIZES[version]
        _require_bytes(data, offset, record_size, "particle preset record")
        cursor = offset

        def read(format_string: str) -> tuple[int | float, ...]:
            nonlocal cursor
            record = struct.Struct("<" + format_string)
            values = record.unpack_from(data, cursor)
            cursor += record.size
            return values

        def read_bytes(size: int) -> bytes:
            nonlocal cursor
            value = data[cursor : cursor + size]
            cursor += size
            return value

        record_id, particle_id = read("2i")
        (critical_flag,) = read("B")
        lifetime, lifetime_variation, initial_age = read("3i")
        spawn_shape, use_transforms_flag = read("2B")
        location = read("3f")
        offset_vector = read("3f")
        location_inherit_flag, location_slave_flag = read("2B")
        linear_maximum = read("3f")
        minimum_radius, maximum_radius = read("2f")
        scale = read("3f")
        (uniform_scale_variation,) = read("f")
        scale_distortion_variation = read("3f")
        scale_inherit_flag, scale_slave_flag = read("2B")
        linear_speed = read("3f")
        radial_speed, speed_variation = read("2f")
        (speed_inherit_flag,) = read("B")
        minimum_angle, maximum_angle = read("2i")
        (use_orientation_flag,) = read("B")
        orientation_quaternion = read("4f")
        orientation_variation_quaternion = read("4f")
        orientation_inherit_flag, orientation_slave_flag = read("2B")
        rotation_quaternion = read("4f")
        rotation_variation_quaternion = read("4f")
        (rotation_inherit_flag,) = read("B")
        spawn_mean_birth, spawn_mean_lifetime = read("2i")
        (spawn_pulse_flag,) = read("B")
        spawn_pulse_on_frames, spawn_pulse_off_frames, spawn_mean_death = read("3i")
        distribute_spawn_flag, use_assigned_object_flag, appearance_inherit_flag = read(
            "3B"
        )
        (object_type_count,) = read("i")
        swap_enabled_flag, random_selection_flag = read("2B")
        (sequence_index,) = read("i")
        solid_flag, ignore_collisions_flag, no_kill_flag = read("3B")
        object_color = read("3B")
        object_translucency, object_luminance = read("2i")
        version_5_item_extension = (
            read_bytes(PARTICLE_PRESET_VERSION_5_ITEM_EXTENSION_SIZE)
            if version == 5
            else b""
        )
        (camera_space_flag,) = read("B")
        item_variants = tuple(
            U9ParticleItemVariantState(*read("Hi"))
            for _ in range(PARTICLE_ITEM_VARIANT_COUNT)
        )
        (use_light_flag,) = read("B")
        light_color = read("3B")
        light_diffusion, light_range = read("2i")
        negative_light_flag, overbright_light_flag = read("2B")
        (sound_template_id,) = read("I")
        sound_category_id, global_sound_flag, loop_sound_flag = read("3B")
        (link_number,) = read("H")
        camera_shock_build, camera_shock_decay = read("2f")
        (camera_shock_intensity,) = read("i")
        (calculate_ramps_by_lifespan_flag,) = read("B")
        ramp_counts = read("7B")
        (random_skeletal_animation_flag,) = read("B")
        light_ramp_counts = read("3B")
        (camera_filter_layer,) = read("i")
        camera_filter_texture = U9ParticleCameraFilterTextureState.from_bytes(
            data, cursor
        )
        cursor += PARTICLE_CAMERA_FILTER_TEXTURE_RECORD.size
        camera_filter_edge_color = read("3B")
        camera_filter_center_color = read("3B")
        (camera_filter_additive_flag,) = read("B")
        (
            camera_filter_color_ramp_count,
            camera_filter_translucency_ramp_count,
        ) = read("2B")
        version_5_ramp_extension = (
            read_bytes(PARTICLE_PRESET_VERSION_5_RAMP_EXTENSION_SIZE)
            if version == 5
            else b""
        )
        ramp_slots = tuple(
            U9ParticleRampSlotState.from_bytes(
                data, cursor + index * PARTICLE_RAMP_SLOT_RECORD.size
            )
            for index in range(PARTICLE_RAMP_SLOT_COUNT)
        )
        cursor += PARTICLE_RAMP_SLOT_COUNT * PARTICLE_RAMP_SLOT_RECORD.size
        (use_parent_skeleton_flag,) = read("B")
        (skeleton_appearance_id,) = read("H")
        skeleton_limb_id, skeleton_attachment_id = read("2i")
        source_object_reference_index, skeleton_object_reference_index = read("2i")
        if cursor != offset + record_size:
            raise U9ProcessDataError(
                f"particle preset parser ended at 0x{cursor:X}; "
                f"expected 0x{offset + record_size:X}"
            )
        if not 0 <= object_type_count <= PARTICLE_ITEM_VARIANT_COUNT:
            raise U9ProcessDataError(
                f"particle preset {record_id} has object-type count "
                f"{object_type_count}; expected 0..{PARTICLE_ITEM_VARIANT_COUNT}"
            )
        # The two camera-filter counts are not checked: a preset that never
        # uses a camera filter can store 255 there (seen in a retail save).
        all_ramp_counts = (*ramp_counts, *light_ramp_counts)
        if any(count > PARTICLE_RAMP_SLOT_COUNT for count in all_ramp_counts):
            raise U9ProcessDataError(
                f"particle preset {record_id} has a ramp count above "
                f"{PARTICLE_RAMP_SLOT_COUNT}"
            )
        return cls(
            version=version,
            record_id=int(record_id),
            particle_id=int(particle_id),
            critical_flag=int(critical_flag),
            lifetime=int(lifetime),
            lifetime_variation=int(lifetime_variation),
            initial_age=int(initial_age),
            spawn_shape=int(spawn_shape),
            use_transforms_flag=int(use_transforms_flag),
            location=tuple(float(value) for value in location),
            offset_vector=tuple(float(value) for value in offset_vector),
            location_inherit_flag=int(location_inherit_flag),
            location_slave_flag=int(location_slave_flag),
            linear_maximum=tuple(float(value) for value in linear_maximum),
            minimum_radius=float(minimum_radius),
            maximum_radius=float(maximum_radius),
            scale=tuple(float(value) for value in scale),
            uniform_scale_variation=float(uniform_scale_variation),
            scale_distortion_variation=tuple(
                float(value) for value in scale_distortion_variation
            ),
            scale_inherit_flag=int(scale_inherit_flag),
            scale_slave_flag=int(scale_slave_flag),
            linear_speed=tuple(float(value) for value in linear_speed),
            radial_speed=float(radial_speed),
            speed_variation=float(speed_variation),
            speed_inherit_flag=int(speed_inherit_flag),
            minimum_angle=int(minimum_angle),
            maximum_angle=int(maximum_angle),
            use_orientation_flag=int(use_orientation_flag),
            orientation_quaternion=tuple(
                float(value) for value in orientation_quaternion
            ),
            orientation_variation_quaternion=tuple(
                float(value) for value in orientation_variation_quaternion
            ),
            orientation_inherit_flag=int(orientation_inherit_flag),
            orientation_slave_flag=int(orientation_slave_flag),
            rotation_quaternion=tuple(float(value) for value in rotation_quaternion),
            rotation_variation_quaternion=tuple(
                float(value) for value in rotation_variation_quaternion
            ),
            rotation_inherit_flag=int(rotation_inherit_flag),
            spawn_mean_birth=int(spawn_mean_birth),
            spawn_mean_lifetime=int(spawn_mean_lifetime),
            spawn_pulse_flag=int(spawn_pulse_flag),
            spawn_pulse_on_frames=int(spawn_pulse_on_frames),
            spawn_pulse_off_frames=int(spawn_pulse_off_frames),
            spawn_mean_death=int(spawn_mean_death),
            distribute_spawn_flag=int(distribute_spawn_flag),
            use_assigned_object_flag=int(use_assigned_object_flag),
            appearance_inherit_flag=int(appearance_inherit_flag),
            object_type_count=int(object_type_count),
            swap_enabled_flag=int(swap_enabled_flag),
            random_selection_flag=int(random_selection_flag),
            sequence_index=int(sequence_index),
            solid_flag=int(solid_flag),
            ignore_collisions_flag=int(ignore_collisions_flag),
            no_kill_flag=int(no_kill_flag),
            object_color=tuple(int(value) for value in object_color),
            object_translucency=int(object_translucency),
            object_luminance=int(object_luminance),
            version_5_item_extension=version_5_item_extension,
            camera_space_flag=int(camera_space_flag),
            item_variants=item_variants,
            use_light_flag=int(use_light_flag),
            light_color=tuple(int(value) for value in light_color),
            light_diffusion=int(light_diffusion),
            light_range=int(light_range),
            negative_light_flag=int(negative_light_flag),
            overbright_light_flag=int(overbright_light_flag),
            sound_template_id=int(sound_template_id),
            sound_category_id=int(sound_category_id),
            global_sound_flag=int(global_sound_flag),
            loop_sound_flag=int(loop_sound_flag),
            link_number=int(link_number),
            camera_shock_build=float(camera_shock_build),
            camera_shock_decay=float(camera_shock_decay),
            camera_shock_intensity=int(camera_shock_intensity),
            calculate_ramps_by_lifespan_flag=int(calculate_ramps_by_lifespan_flag),
            spawn_mean_ramp_count=int(ramp_counts[0]),
            lifespan_keyframes=int(ramp_counts[1]),
            object_scale_ramp_count=int(ramp_counts[2]),
            object_color_ramp_count=int(ramp_counts[3]),
            object_translucency_ramp_count=int(ramp_counts[4]),
            object_luminance_ramp_count=int(ramp_counts[5]),
            skeletal_animation_count=int(ramp_counts[6]),
            random_skeletal_animation_flag=int(random_skeletal_animation_flag),
            light_color_keyframes=int(light_ramp_counts[0]),
            light_range_keyframes=int(light_ramp_counts[1]),
            light_diffusion_keyframes=int(light_ramp_counts[2]),
            camera_filter_layer=int(camera_filter_layer),
            camera_filter_texture=camera_filter_texture,
            camera_filter_edge_color=tuple(
                int(value) for value in camera_filter_edge_color
            ),
            camera_filter_center_color=tuple(
                int(value) for value in camera_filter_center_color
            ),
            camera_filter_additive_flag=int(camera_filter_additive_flag),
            camera_filter_color_ramp_count=int(camera_filter_color_ramp_count),
            camera_filter_translucency_ramp_count=int(
                camera_filter_translucency_ramp_count
            ),
            version_5_ramp_extension=version_5_ramp_extension,
            ramp_slots=ramp_slots,
            use_parent_skeleton_flag=int(use_parent_skeleton_flag),
            skeleton_appearance_id=int(skeleton_appearance_id),
            skeleton_limb_id=int(skeleton_limb_id),
            skeleton_attachment_id=int(skeleton_attachment_id),
            source_object_reference_index=int(source_object_reference_index),
            skeleton_object_reference_index=int(skeleton_object_reference_index),
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_PRESET_RECORD_SIZES[self.version]


@dataclass(frozen=True)
class U9ParticleForcePresetState:
    """One particle force preset, including its object attachment reference."""

    record_id: int
    force_type: int
    lifetime: int
    initial_age: int
    trigger_age: int
    location: tuple[float, float, float]
    strength: float
    influence_distance: int
    inner_radius: int
    scale: tuple[float, float, float]
    speed_limit: int
    twist_velocity: tuple[float, float, float]
    offset_vector: tuple[float, float, float]
    element_id: int
    hard_point_id: int
    numeric_type: int
    object_reference_index: int
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleForcePresetState:
        _require_bytes(
            data,
            offset,
            PARTICLE_FORCE_PRESET_RECORD.size,
            "particle force preset record",
        )
        values = PARTICLE_FORCE_PRESET_RECORD.unpack_from(data, offset)
        return cls(
            record_id=values[0],
            force_type=values[1],
            lifetime=values[2],
            initial_age=values[3],
            trigger_age=values[4],
            location=tuple(values[5:8]),
            strength=values[8],
            influence_distance=values[9],
            inner_radius=values[10],
            scale=tuple(values[11:14]),
            speed_limit=values[14],
            twist_velocity=tuple(values[15:18]),
            offset_vector=tuple(values[18:21]),
            element_id=values[21],
            hard_point_id=values[22],
            numeric_type=values[23],
            object_reference_index=values[24],
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_FORCE_PRESET_RECORD.size


@dataclass(frozen=True)
class U9ParticleForceState:
    """One active particle force and its link to a force preset."""

    record_id: int
    age: int
    location: tuple[float, float, float]
    preset_id: int
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleForceState:
        _require_bytes(
            data, offset, PARTICLE_FORCE_RECORD.size, "particle force record"
        )
        values = PARTICLE_FORCE_RECORD.unpack_from(data, offset)
        return cls(
            record_id=values[0],
            age=values[1],
            location=(values[2], values[3], values[4]),
            preset_id=values[5],
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_FORCE_RECORD.size


@dataclass(frozen=True)
class U9ParticleGenerationState:
    """One particle-generation record and its linked effects."""

    record_id: int
    particle_preset_id: int
    birth_generation_id: int
    lifetime_generation_id: int
    death_generation_id: int
    birth_force_ids: tuple[int, ...]
    lifetime_force_ids: tuple[int, ...]
    death_force_ids: tuple[int, ...]
    slave_force_ids: tuple[int, ...]
    slave_generation_ids: tuple[int, ...]
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleGenerationState:
        _require_bytes(
            data,
            offset,
            PARTICLE_GENERATION_RECORD.size,
            "particle generation record",
        )
        values = PARTICLE_GENERATION_RECORD.unpack_from(data, offset)
        force_ids = values[5:21]
        return cls(
            record_id=values[0],
            particle_preset_id=values[1],
            birth_generation_id=values[2],
            lifetime_generation_id=values[3],
            death_generation_id=values[4],
            birth_force_ids=tuple(force_ids[0::4]),
            lifetime_force_ids=tuple(force_ids[1::4]),
            death_force_ids=tuple(force_ids[2::4]),
            slave_force_ids=tuple(force_ids[3::4]),
            slave_generation_ids=tuple(values[21:31]),
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_GENERATION_RECORD.size


@dataclass(frozen=True)
class U9ParticleInstanceState:
    """One active particle instance and its runtime object relationships."""

    record_id: int
    generation_id: int
    parent_particle_id: int
    child_particle_ids: tuple[int, ...]
    lifetime: int
    age: int
    location: tuple[float, float, float]
    velocity: tuple[float, float, float]
    snap_velocity: tuple[float, float, float]
    scale: tuple[float, float, float]
    orientation_quaternion: tuple[float, float, float, float]
    rotation_quaternion: tuple[float, float, float, float]
    spawn_mean_lifetime: int
    spawn_pulse_count: int
    spawn_pulse_count_byte: int
    object_type_id: int
    object_status_flags: int
    alternate_sequence: int
    sequence_index: int
    swap_elapsed_frames: int
    attached_element_id: int
    sound_id: int
    light_source_flag: int
    callback_id: int
    callback_effect_id: int
    callback_spell_kind: int
    callback_caster_reference_index: int
    object_reference_index: int
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleInstanceState:
        _require_bytes(
            data,
            offset,
            PARTICLE_INSTANCE_RECORD.size,
            "particle instance record",
        )
        values = PARTICLE_INSTANCE_RECORD.unpack_from(data, offset)
        return cls(
            record_id=values[0],
            generation_id=values[1],
            parent_particle_id=values[2],
            child_particle_ids=tuple(values[3:13]),
            lifetime=values[13],
            age=values[14],
            location=tuple(values[15:18]),
            velocity=tuple(values[18:21]),
            snap_velocity=tuple(values[21:24]),
            scale=tuple(values[24:27]),
            orientation_quaternion=tuple(values[27:31]),
            rotation_quaternion=tuple(values[31:35]),
            spawn_mean_lifetime=values[35],
            spawn_pulse_count=values[36],
            spawn_pulse_count_byte=values[37],
            object_type_id=values[38],
            object_status_flags=values[39],
            alternate_sequence=values[40],
            sequence_index=values[41],
            swap_elapsed_frames=values[42],
            attached_element_id=values[43],
            sound_id=values[44],
            light_source_flag=values[45],
            callback_id=values[46],
            callback_effect_id=values[47],
            callback_spell_kind=values[48],
            callback_caster_reference_index=values[49],
            object_reference_index=values[50],
            offset=offset,
        )

    @property
    def pulse_count_byte_matches(self) -> bool:
        """Whether the redundant byte matches the pulse counter's low byte."""
        return self.spawn_pulse_count_byte == (self.spawn_pulse_count & 0xFF)

    @property
    def has_light_source(self) -> bool:
        return bool(self.light_source_flag)

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_INSTANCE_RECORD.size


@dataclass(frozen=True)
class U9ParticleRecordCollection:
    """One counted, fixed-stride particle-system record collection."""

    name: str
    record_size: int
    record_ids: tuple[int, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        name: str,
        count: int,
        record_size: int,
    ) -> U9ParticleRecordCollection:
        byte_count = count * record_size
        _require_bytes(data, offset, byte_count, name)
        record_ids = tuple(
            struct.unpack_from("<i", data, offset + index * record_size)[0]
            for index in range(count)
        )
        for index, record_id in enumerate(record_ids, start=1):
            if record_id != index:
                raise U9ProcessDataError(
                    f"{name} record {index} has ID {record_id}; expected {index}"
                )
        return cls(
            name=name,
            record_size=record_size,
            record_ids=record_ids,
            offset=offset,
            end_offset=offset + byte_count,
        )

    @property
    def count(self) -> int:
        return len(self.record_ids)


@dataclass(frozen=True)
class U9ParticleRecordCollections:
    """The five serialized particle-system collections in stream order."""

    particle_presets: U9ParticleRecordCollection
    force_presets: U9ParticleRecordCollection
    forces: U9ParticleRecordCollection
    generations: U9ParticleRecordCollection
    particles: U9ParticleRecordCollection
    particle_preset_records: tuple[U9ParticlePresetState, ...]
    force_preset_records: tuple[U9ParticleForcePresetState, ...]
    force_records: tuple[U9ParticleForceState, ...]
    generation_records: tuple[U9ParticleGenerationState, ...]
    particle_records: tuple[U9ParticleInstanceState, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        version: int,
        particle_preset_count: int,
        generation_count: int,
        particle_count: int,
        force_preset_count: int,
        force_count: int,
        object_reference_count: int | None = None,
    ) -> U9ParticleRecordCollections:
        cursor = offset

        def read_collection(
            name: str, count: int, record_size: int
        ) -> U9ParticleRecordCollection:
            nonlocal cursor
            collection = U9ParticleRecordCollection.from_bytes(
                data,
                cursor,
                name=name,
                count=count,
                record_size=record_size,
            )
            cursor = collection.end_offset
            return collection

        particle_presets = read_collection(
            "particle presets",
            particle_preset_count,
            PARTICLE_PRESET_RECORD_SIZES[version],
        )
        force_presets = read_collection(
            "particle force presets",
            force_preset_count,
            PARTICLE_FORCE_PRESET_RECORD_SIZE,
        )
        forces = read_collection(
            "particle forces", force_count, PARTICLE_FORCE_RECORD_SIZE
        )
        generations = read_collection(
            "particle generations",
            generation_count,
            PARTICLE_GENERATION_RECORD_SIZE,
        )
        particles = read_collection(
            "particle instances", particle_count, PARTICLE_INSTANCE_RECORD_SIZE
        )
        particle_preset_records = tuple(
            U9ParticlePresetState.from_bytes(
                data,
                particle_presets.offset + index * PARTICLE_PRESET_RECORD_SIZES[version],
                version=version,
            )
            for index in range(particle_preset_count)
        )
        force_preset_records = tuple(
            U9ParticleForcePresetState.from_bytes(
                data,
                force_presets.offset + index * PARTICLE_FORCE_PRESET_RECORD_SIZE,
            )
            for index in range(force_preset_count)
        )
        force_records = tuple(
            U9ParticleForceState.from_bytes(
                data, forces.offset + index * PARTICLE_FORCE_RECORD_SIZE
            )
            for index in range(force_count)
        )
        generation_records = tuple(
            U9ParticleGenerationState.from_bytes(
                data, generations.offset + index * PARTICLE_GENERATION_RECORD_SIZE
            )
            for index in range(generation_count)
        )
        particle_records = tuple(
            U9ParticleInstanceState.from_bytes(
                data, particles.offset + index * PARTICLE_INSTANCE_RECORD_SIZE
            )
            for index in range(particle_count)
        )
        if object_reference_count is not None:
            for record in particle_preset_records:
                cls._validate_index_reference(
                    record.source_object_reference_index,
                    object_reference_count,
                    f"particle preset {record.record_id} source object",
                )
                cls._validate_index_reference(
                    record.skeleton_object_reference_index,
                    object_reference_count,
                    f"particle preset {record.record_id} skeleton object",
                )
            for record in force_preset_records:
                cls._validate_index_reference(
                    record.object_reference_index,
                    object_reference_count,
                    f"particle force preset {record.record_id} object",
                )
        for record in force_records:
            cls._validate_reference(
                record.preset_id,
                force_preset_count,
                f"particle force {record.record_id} force preset",
            )
        for record in generation_records:
            cls._validate_reference(
                record.particle_preset_id,
                particle_preset_count,
                f"particle generation {record.record_id} particle preset",
            )
            for label, references, count in (
                (
                    "birth generation",
                    (record.birth_generation_id,),
                    generation_count,
                ),
                (
                    "lifetime generation",
                    (record.lifetime_generation_id,),
                    generation_count,
                ),
                (
                    "death generation",
                    (record.death_generation_id,),
                    generation_count,
                ),
                ("slave generation", record.slave_generation_ids, generation_count),
                ("birth force", record.birth_force_ids, force_count),
                ("lifetime force", record.lifetime_force_ids, force_count),
                ("death force", record.death_force_ids, force_count),
                ("slave force", record.slave_force_ids, force_count),
            ):
                for reference in references:
                    cls._validate_reference(
                        reference,
                        count,
                        f"particle generation {record.record_id} {label}",
                        allow_null=True,
                    )
        for record in particle_records:
            cls._validate_reference(
                record.generation_id,
                generation_count,
                f"particle instance {record.record_id} generation",
            )
            cls._validate_reference(
                record.parent_particle_id,
                particle_count,
                f"particle instance {record.record_id} parent particle",
                allow_null=True,
            )
            for child_id in record.child_particle_ids:
                cls._validate_reference(
                    child_id,
                    particle_count,
                    f"particle instance {record.record_id} child particle",
                    allow_null=True,
                )
            if object_reference_count is not None:
                cls._validate_index_reference(
                    record.callback_caster_reference_index,
                    object_reference_count,
                    f"particle instance {record.record_id} callback caster",
                )
                cls._validate_index_reference(
                    record.object_reference_index,
                    object_reference_count,
                    f"particle instance {record.record_id} object",
                )
        return cls(
            particle_presets=particle_presets,
            force_presets=force_presets,
            forces=forces,
            generations=generations,
            particles=particles,
            particle_preset_records=particle_preset_records,
            force_preset_records=force_preset_records,
            force_records=force_records,
            generation_records=generation_records,
            particle_records=particle_records,
            offset=offset,
            end_offset=cursor,
        )

    @staticmethod
    def _validate_reference(
        reference: int,
        count: int,
        label: str,
        *,
        allow_null: bool = False,
    ) -> None:
        if allow_null and reference == -1:
            return
        if not 1 <= reference <= count:
            null_note = " or -1" if allow_null else ""
            raise U9ProcessDataError(
                f"{label} reference {reference} is outside 1..{count}{null_note}"
            )

    @staticmethod
    def _validate_index_reference(reference: int, count: int, label: str) -> None:
        if not 0 <= reference < count:
            raise U9ProcessDataError(
                f"{label} reference {reference} is outside 0..{count - 1}"
            )


@dataclass(frozen=True)
class U9ParticleProcessState:
    """Global counters preceding the first process's particle records."""

    version: int
    animation_time: int
    translation_flag: int
    next_particle_id: int
    particle_preset_count: int
    generation_count: int
    particle_count: int
    force_preset_count: int
    force_count: int
    offset: int
    records: U9ParticleRecordCollections

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int | None = None,
    ) -> U9ParticleProcessState:
        _require_bytes(data, offset, PARTICLE_PROCESS_STATE_SIZE, "particle state")
        version, animation_time = struct.unpack_from("<iI", data, offset)
        if version not in PARTICLE_PROCESS_VERSIONS:
            raise U9ProcessDataError(
                f"unsupported particle-state version {version} at 0x{offset:X}"
            )
        translation_flag = data[offset + 8]
        next_particle_id = struct.unpack_from("<i", data, offset + 9)[0]
        counts = struct.unpack_from("<5i", data, offset + 13)
        if any(count < 0 for count in counts):
            raise U9ProcessDataError(f"negative particle-state record count {counts}")
        records = U9ParticleRecordCollections.from_bytes(
            data,
            offset + PARTICLE_PROCESS_STATE_SIZE,
            version=version,
            particle_preset_count=counts[0],
            generation_count=counts[1],
            particle_count=counts[2],
            force_preset_count=counts[3],
            force_count=counts[4],
            object_reference_count=object_reference_count,
        )
        return cls(
            version=version,
            animation_time=animation_time,
            translation_flag=translation_flag,
            next_particle_id=next_particle_id,
            particle_preset_count=counts[0],
            generation_count=counts[1],
            particle_count=counts[2],
            force_preset_count=counts[3],
            force_count=counts[4],
            offset=offset,
            records=records,
        )

    @property
    def translation_pending(self) -> bool:
        return bool(self.translation_flag)

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_PROCESS_STATE_SIZE
