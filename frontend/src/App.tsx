import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Ion,
  Viewer as CesiumViewer,
  Terrain,
  Cartesian3,
  Color,
  HeightReference,
  VerticalOrigin,
  NearFarScalar,
  Cartesian2,
  Math as CesiumMath,
  Entity,
  ScreenSpaceEventType,
  defined,
  LabelStyle,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'

Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_ION_TOKEN ?? ''

const POLL_INTERVAL = 5_000
const API_ENDPOINT = '/api/geojson/ski_resorts'

interface SkiResort {
  id: number
  name: string
  province?: string
  nearest_city?: string
  country?: string
  vertical_drop_m?: number
  num_runs?: number
  num_lifts?: number
  lon: number
  lat: number
}

export default function App() {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<CesiumViewer | null>(null)
  const entitiesRef = useRef<Map<number, Entity>>(new Map())
  const [selected, setSelected] = useState<SkiResort | null>(null)
  const [count, setCount] = useState(0)
  const resortsRef = useRef<SkiResort[]>([])

  // ── Initialize Cesium viewer once ──────────────────────────
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return

    const viewer = new CesiumViewer(containerRef.current, {
      terrain: Terrain.fromWorldTerrain(),
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      sceneModePicker: false,
      selectionIndicator: true,
      infoBox: false,
    })

    viewer.scene.globe.depthTestAgainstTerrain = true
    viewer.scene.globe.enableLighting = true

    // Fly to Whistler area
    viewer.camera.flyTo({
      destination: Cartesian3.fromDegrees(-122.96, 48.08, 250_000),
      orientation: {
        heading: CesiumMath.toRadians(0),
        pitch: CesiumMath.toRadians(-45),
        roll: 0,
      },
      duration: 0,
    })

    // Click handler
    viewer.screenSpaceEventHandler.setInputAction(
      (click: { position: Cartesian2 }) => {
        const picked = viewer.scene.pick(click.position)
        if (defined(picked) && picked.id instanceof Entity) {
          const id = (picked.id as any)._resortId as number
          const resort = resortsRef.current.find((r) => r.id === id)
          if (resort) setSelected(resort)
        } else {
          setSelected(null)
        }
      },
      ScreenSpaceEventType.LEFT_CLICK,
    )

    viewerRef.current = viewer

    return () => {
      viewer.destroy()
      viewerRef.current = null
    }
  }, [])

  // ── Fetch & sync entities ──────────────────────────────────
  const syncEntities = useCallback((items: SkiResort[]) => {
    const viewer = viewerRef.current
    if (!viewer) return

    resortsRef.current = items
    setCount(items.length)

    const currentIds = new Set(items.map((r) => r.id))

    // Remove entities no longer in data
    for (const [id, entity] of entitiesRef.current) {
      if (!currentIds.has(id)) {
        viewer.entities.remove(entity)
        entitiesRef.current.delete(id)
      }
    }

    // Add/update entities
    for (const r of items) {
      if (entitiesRef.current.has(r.id)) continue // already added

      const entity = viewer.entities.add({
        position: Cartesian3.fromDegrees(r.lon, r.lat, 0),
        point: {
          pixelSize: 10,
          color: Color.fromCssColorString('#00b4ff'),
          outlineColor: Color.WHITE,
          outlineWidth: 2,
          heightReference: HeightReference.CLAMP_TO_GROUND,
          scaleByDistance: new NearFarScalar(1_000, 1.5, 5_000_000, 0.4),
        },
        label: {
          text: r.name,
          font: '13px sans-serif',
          fillColor: Color.WHITE,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -14),
          heightReference: HeightReference.CLAMP_TO_GROUND,
          scaleByDistance: new NearFarScalar(1_000, 1, 3_000_000, 0.3),
          translucencyByDistance: new NearFarScalar(1_000, 1, 5_000_000, 0),
        },
      })
      ;(entity as any)._resortId = r.id
      entitiesRef.current.set(r.id, entity)
    }
  }, [])

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(API_ENDPOINT)
      if (!res.ok) return
      const geojson = await res.json()
      const items: SkiResort[] = geojson.features
        .filter((f: any) => f.geometry)
        .map((f: any) => ({
          id: f.properties.id,
          name: f.properties.name,
          province: f.properties.province,
          nearest_city: f.properties.nearest_city,
          country: f.properties.country,
          vertical_drop_m: f.properties.vertical_drop_m,
          num_runs: f.properties.num_runs,
          num_lifts: f.properties.num_lifts,
          lon: f.geometry.coordinates[0],
          lat: f.geometry.coordinates[1],
        }))
      syncEntities(items)
    } catch (e) {
      console.error('Fetch error:', e)
    }
  }, [syncEntities])

  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [fetchData])

  return (
    <>
      {/* ── info panel ───────────────────────────────────────── */}
      <div style={panelStyle}>
        <strong style={{ fontSize: 15 }}>🎿 Ski Resorts</strong>
        <div style={{ marginTop: 6, fontSize: 13, color: '#ccc' }}>
          {count} resort{count !== 1 ? 's' : ''} · polling every{' '}
          {POLL_INTERVAL / 1000}s
        </div>
        <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
          Add a row in PostgreSQL → appears here automatically
        </div>
        {selected && (
          <div
            style={{
              marginTop: 10,
              borderTop: '1px solid #555',
              paddingTop: 8,
            }}
          >
            <div style={{ fontWeight: 600 }}>{selected.name}</div>
            {(selected.province || selected.country) && (
              <div>{[selected.province, selected.country].filter(Boolean).join(', ')}</div>
            )}
            {selected.vertical_drop_m != null && (
              <div>↕ {selected.vertical_drop_m} m drop</div>
            )}
            {selected.num_runs != null && (
              <div>
                {selected.num_runs} runs · {selected.num_lifts ?? '?'} lifts
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Cesium container ─────────────────────────────────── */}
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </>
  )
}

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 12,
  left: 12,
  zIndex: 5,
  background: 'rgba(0,0,0,0.75)',
  color: '#fff',
  padding: '12px 16px',
  borderRadius: 8,
  fontFamily: 'system-ui, sans-serif',
  maxWidth: 280,
}

