"""Fit non-AI sketch detail to the configured budget, never a guessed game timer."""
import math
import time
from PIL import Image,ImageDraw
from PixelData import monochrome_strokes


def _trial_images(plan):
    """Only the renderer-owned image fields; do not traverse arbitrary options."""
    if not isinstance(plan,dict):return []
    images=[plan.get('image'),plan.get('preview')]
    previews=plan.get('ui_previews')
    if isinstance(previews,dict):images.extend(previews.values())
    opts=plan.get('options')
    if isinstance(opts,dict):
        for key in ('_accuracy_original_source','_pixel_coverage_preview','_pixel_error_preview'):
            images.append(opts.get(key))
    return [image for image in images if isinstance(image,Image.Image)]


def _preserved_image_ids(original,options,retained=None):
    borrowed=[original]+[value for value in options.values() if isinstance(value,Image.Image)]
    return {id(image) for image in borrowed+_trial_images(retained) if isinstance(image,Image.Image)}


def _release_trial(plan,original,options,retained=None):
    preserved=_preserved_image_ids(original,options,retained)
    for image in _trial_images(plan):
        if id(image) not in preserved:
            image.close();preserved.add(id(image))


def _validate_estimate(plan):
    value=plan.get('estimate')
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError('Sketch estimate must be finite and non-negative.')
    try:valid=math.isfinite(value) and value>=0
    except (TypeError,ValueError,OverflowError):valid=False
    if not valid:raise ValueError('Sketch estimate must be finite and non-negative.')


def choose_sketch(original,area,options,planner,finisher,cancelled=lambda:False):
    if cancelled():raise InterruptedError()
    if options.get('unlimited_time') or options.get('time_budget_mode') in ('Unlimited','Unlimited / Accuracy'):
        plan=planner(original,area,dict(options,sketch_detail='Detailed'),cancelled)
        try:
            _validate_estimate(plan)
            if cancelled():raise InterruptedError()
            plan['options']['sketch_auto_meta']={'selected_detail':'Detailed','estimated_seconds':plan['estimate'],'paths_omitted':0,'full_paths':plan['count'],'timer_source':'Unlimited'}
            return plan
        except BaseException:
            _release_trial(plan,original,options)
            raise
    seconds=float(options.get('max_seconds',180))
    if not math.isfinite(seconds) or seconds<=0:raise ValueError('Sketch time budget must be positive and finite.')
    started=time.monotonic();trials=[]
    def remaining():return seconds*.85-(time.monotonic()-started)
    def check():
        if cancelled():raise InterruptedError()
    def done(plan,detail,trimmed,total):
        plan['options']['sketch_detail']='Auto'
        plan['options']['sketch_auto_meta']={'selected_detail':detail,'configured_seconds':seconds,
            'drawing_budget_seconds':max(0,remaining()),'estimated_seconds':plan['estimate'],
            'planning_seconds':time.monotonic()-started,'reserve_percent':15,
            'paths_omitted':trimmed,'full_paths':total,'trials':trials,
            'timer_source':'configured in app; no game timer reading'}
        return plan
    plan=full=reduced=retained=raster=None
    try:
        for detail in ('Detailed','Balanced','Simple'):
            check()
            candidate=planner(original,area,dict(options,sketch_detail=detail),cancelled)
            _release_trial(plan,original,options,candidate)
            plan=candidate
            _validate_estimate(plan)
            check()
            trials.append({'detail':detail,'estimate':plan['estimate'],'paths':plan['count']})
            if plan['estimate']<=remaining():
                retained=done(plan,detail,0,plan['count']);return retained
        # Every full-detail candidate exceeds the budget. Keep whole paths, with
        # the same contour priority as the Gartic engine; never interrupt a segment
        # during planning or falsify its cost. Each reduced plan is estimated again.
        full=plan
        paths=[(i,path) for i,group in enumerate(full.get('execution_groups') or []) for path in group]
        if not paths:
            if full['count']==0:
                retained=done(full,'Simple',0,0);return retained
            raise ValueError('Auto sketch could not build continuous paths. Choose Simple or increase the time budget.')
        count=len(paths);keep=max(1,min(count-1,int(count*max(0,remaining()-3)/max(.01,full['estimate']-3)*.9)))
        for _ in range(8):
            check()
            groups=[[] for _ in full['groups']]
            _release_trial(reduced,original,options,full)
            reduced=None
            if raster is not None:raster.close()
            raster=Image.new('RGBA',full['image'].size,'white');draw=ImageDraw.Draw(raster)
            for path_number,(i,path) in enumerate(paths[:keep]):
                if path_number%128==0:check()
                if len(path)==1:draw.point(path[0],fill='black')
                else:draw.line(path,fill='black',width=1)
                groups[i].append(path)
            raw=[[] for _ in groups]
            # Sketch plans contain exactly one active ink colour.
            active=next((i for i,g in enumerate(groups) if g),0)
            raw[active]=monochrome_strokes(raster,True,cancelled)[0]
            reduced_options=dict(full['options'],sketch_execution_groups=groups,stroke_optimizer='Off',target_stroke_count_resolved=None)
            if reduced_options.get('gartic_sketch_meta'):
                reduced_options['gartic_sketch_meta']=dict(reduced_options['gartic_sketch_meta'],execution_paths=keep)
            reduced=finisher(raster,full['fitted'],raw,reduced_options,cancelled)
            _validate_estimate(reduced)
            check()
            if reduced['estimate']<=remaining():
                retained=done(reduced,'Simple',count-keep,count);return retained
            if keep<=1:break
            keep=max(1,min(keep-1,int(keep*max(0,remaining()-3)/max(.01,reduced['estimate']-3)*.85)))
        raise ValueError('Too little time remains for a safe sketch, even with Auto detail. Increase the time in the app or use a simpler image.')
    finally:
        _release_trial(plan,original,options,retained)
        if full is not plan:_release_trial(full,original,options,retained)
        _release_trial(reduced,original,options,retained)
        if raster is not None and id(raster) not in _preserved_image_ids(original,options,retained):raster.close()
