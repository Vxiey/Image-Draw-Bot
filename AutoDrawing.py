"""Deterministic image-based presets; no AI or changes to native input safeguards."""
import numpy as np
from PIL import Image
from DrawingStyleProfiles import apply_drawing_style
from ExtraFastProfilePolicy import apply_extra_fast_profile_policy

PRESETS=('Auto','Manual','Masterpiece','Extra fast')

def resolve_drawing(image,options):
    raw=dict(options);preset=raw.get('render_preset','Manual')
    if preset not in PRESETS:raise ValueError('Choose Auto, Manual, Masterpiece or Extra fast.')
    # Manual means the caller owns every setting. Auto Drawing Style must not
    # inject resolved style metadata or alter manual controls unless the user
    # explicitly selected a non-Auto drawing style.
    if preset=='Manual' and raw.get('drawing_style','Auto')=='Auto':return raw
    out=apply_drawing_style(image,raw);preset=out.get('render_preset','Manual')
    if out.get('drawing_style')!='Auto' and preset in ('Auto','Manual'):
        out['auto_engine_resolved']=True
        out['auto_drawing_meta']={'preset':preset,'image_kind':out.get('drawing_style_resolved'),
            'engine':'drawing style profile','drawing_style_profile':out.get('drawing_style_meta')}
        return out
    if preset=='Manual' or out.get('auto_engine_resolved'):return out
    out['auto_engine_resolved']=True
    if preset=='Extra fast':
        if out.get('erase_mode'):
            raise ValueError('Extra fast needs Brush or Pencil, not Eraser.')
        # Extra Fast keeps the proven color pipeline but is no longer one global
        # scanline preset.  Target profile + Drawing Style select the recognition
        # policy that feeds Adaptive Region Hybrid / Pixel Accurate / contour
        # planning.  Native-input safety and calibration remain outside this layer.
        out.update(extra_fast=True,extra_fast_v2=True,
            subject_focus='Off',draw_quality='High likeness',
            drawing_mode='Smart paths (recommended)',smart_paths=True,lines=True,
            color_layers='Off',
            background_fill='Balanced' if out.get('fill_tool_available') else 'Off',
            fill_engine='Closed regions v2',human_mode='Off',stroke_optimizer='Smart merge + 2-opt')
        out.setdefault('color_rendering','Perceptual match')
        out.setdefault('color_fidelity','Faithful')
        out.setdefault('custom_color_workflow','Adaptive exact (recommended)' if out.get('exact_color_available') else 'Calibrated palette')
        out.setdefault('exact_color_limit','Auto')
        out,fast_strategy=apply_extra_fast_profile_policy(out)
        engine=str(fast_strategy.get('engine') or 'Extra Fast regional hybrid')
        if out.get('paint_current_color') or out.get('outline'):
            out.update(outline=True,sketch_detail=out.get('sketch_detail') or 'Simple',background_fill='Off')
            if out.get('paint_current_color'):
                engine='Simple black contours (single-colour mode)'
        out['auto_drawing_meta']={
            'preset':preset,'image_kind':out.get('drawing_style_resolved') or 'palette drawing',
            'engine':engine,'recognition_first':True,'extra_fast_strategy':fast_strategy,
        }
        return out
    rgba=image.convert('RGBA');flat=Image.new('RGBA',rgba.size,'white');flat.alpha_composite(rgba)
    flat.thumbnail((128,128));a=np.asarray(flat.convert('RGB'),dtype=np.int16)
    white=float(np.mean(np.min(a,axis=2)>235))
    chroma=float(np.mean(a.max(axis=2)-a.min(axis=2)>35))
    # Quantized colour occupancy is a texture heuristic, not object recognition.
    bins=(a//32).astype(np.int32);codes=bins[:,:,0]*64+bins[:,:,1]*8+bins[:,:,2]
    hist=np.bincount(codes.ravel(),minlength=512);dominant=float(np.sort(hist)[-12:].sum()/hist.sum())
    source_kind='line art' if white>.65 and chroma<.12 else 'flat illustration' if dominant>.90 else 'photo / texture'
    # Step 11: Auto is now an end-to-end quality/speed policy for full-colour
    # images. It composes the existing colour/deadline/calibration engines and
    # leaves explicit Manual/Masterpiece/Extra fast presets untouched. Legacy
    # line-art auto selection remains the dedicated black-contour path.
    if preset=='Auto' and source_kind!='line art' and not (out.get('paint_current_color') or out.get('outline') or out.get('erase_mode')):
        try:
            from EndToEndAutoTuner import tune_options
            tuned=tune_options(image,out,source_kind_hint=source_kind)
            meta=tuned.get('auto_tuner_meta') or {}
            if meta.get('active'):
                engine='Shape paths' if tuned.get('drawing_mode')=='Shape paths' else 'Smart color paths'
                tuned['auto_drawing_meta']={'preset':preset,'image_kind':source_kind,'engine':engine,
                    'white_fraction':white,'dominant_colors_fraction':dominant,'step11_auto_tuner':True,
                    'strategy':meta.get('selected_strategy')}
                return tuned
        except InterruptedError:
            raise
        except Exception:
            # Auto tuning is an optimization layer. Fall back to the established
            # deterministic Auto policy if its bounded analysis is unavailable.
            pass
    if out.get('paint_current_color') or out.get('outline'):
        engine='black contours';out.update(outline=True,subject_focus='Off',sketch_detail='Detailed' if preset=='Masterpiece' else 'Auto')
    elif preset=='Masterpiece' or out.get('unlimited_time') or out.get('time_budget_mode')=='Unlimited':
        engine='Pixel Accurate';out.update(draw_quality='Pixel Accurate',brush_px=1,profile_engine='Manual settings')
    elif source_kind=='line art':
        engine='black contours';out.update(outline=True,subject_focus='Off',sketch_detail='Auto')
    elif source_kind=='flat illustration':
        engine='Shape paths';out.update(drawing_mode='Shape paths',lines=True,draw_quality='High likeness',profile_engine='Manual settings')
    else:
        engine='Smart color paths';out.update(drawing_mode='Smart paths (recommended)',lines=True,smart_paths=True,draw_quality='High likeness',profile_engine='Manual settings',background_simplification='Balanced')
    if preset=='Masterpiece':
        out.update(unlimited_time=True,time_budget_mode='Unlimited',time_budget_active=False,
            background_simplification='Off',adaptive_detail='Off',stroke_optimizer='Travel only',
            target_stroke_count='Auto',target_stroke_count_resolved=None,read_gartic_timer=False)
        out.pop('gartic_timer_deadline',None);out.pop('gartic_timer_meta',None)
    out['auto_drawing_meta']={'preset':preset,'image_kind':source_kind,'engine':engine,'white_fraction':white,'dominant_colors_fraction':dominant}
    return out
