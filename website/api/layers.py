"""Compatibility projection of the checked catalog for the current layer UI."""
from contextlib import ExitStack, contextmanager
from time import monotonic

from secondthought.steering_rewriter import (
    SteeredQwenRewriter, make_steering_hook, GenerationResult, GenerationCancelled,
)
from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention, compile_interventions, steering_context
from secondthought.lab.plans import resolve_plan

DEFAULT_MODEL = 'qwen2.5-0.5b-instruct'


def layer_manifest():
    return get_catalog().layer_manifest(DEFAULT_MODEL)


class ExploreRewriter(SteeredQwenRewriter):
    """Website-only layer experiments; the extension's default service is unchanged."""
    catalog_model_id = DEFAULT_MODEL
    def __init__(self, **kwargs):
        self.catalog = get_catalog()
        self.catalog_version = self.catalog.version
        if any(a.format == 'legacy' and a.id in self.catalog.issues for a in self.catalog.spec.artifacts):
            raise ValueError('A required legacy reference artifact failed catalog validation')
        spec = self.catalog.models[DEFAULT_MODEL]
        super().__init__(model_revision=spec.revision, **kwargs)
        if (self.model_id != spec.repository or len(self.decoder_layers) != spec.layer_count or
                self.model.config.hidden_size != spec.hidden_size):
            raise ValueError('Runtime model does not match the catalog architecture')
        self.layer_vectors = {}
        self.layer_bounds = {}
        for entry in self.catalog.layer_manifest(DEFAULT_MODEL):
            if entry['available']:
                self.layer_vectors[entry['index']] = self.catalog.vector(entry['vector_id'])
                vector = self.catalog.vectors[entry['vector_id']]
                self.layer_bounds[entry['index']] = (vector.strength_min, vector.strength_max)

    def stream_run(self, plan, message, **kwargs):
        if plan.model_id != self.catalog_model_id:
            raise ValueError('The selected model is not loaded in this worker')
        if plan != resolve_plan(self.catalog,plan.model_id,plan.interventions):
            raise ValueError('The resolved plan no longer matches this worker catalog')
        continuation = kwargs.pop('continuation', None)
        if continuation is None:
            return self.stream_rewrite(message,0,0,interventions=plan.interventions,**kwargs)
        # One scheduled job and one intervention plan, with a shared token and
        # time budget. Every stage uses the normal locked, cleanup-safe runtime.
        started = monotonic()
        budget = kwargs['max_new_tokens']
        rewritten = self.stream_rewrite(message,0,0,interventions=plan.interventions,
            **(kwargs | dict(max_new_tokens=max(1,budget//2))))
        if rewritten.finish_reason != 'stop':
            return rewritten  # Never append to a rewrite cut off mid-sentence.
        if kwargs['cancelled'].is_set():
            raise GenerationCancelled()
        remaining_time = kwargs['timeout_seconds'] - (monotonic()-started)
        if remaining_time <= 0:
            raise TimeoutError('Rewrite and continuation exceeded the generation deadline')
        suffix_started = False
        separator = continuation['separator']
        def on_suffix(text):
            nonlocal suffix_started
            if not text:
                return
            if not suffix_started:
                kwargs['on_text'](separator)
                suffix_started = True
            kwargs['on_text'](text)
        suffix = self.stream_rewrite(rewritten.text+separator,0,0,interventions=plan.interventions,
            **(kwargs | dict(system_prompt=continuation['continuation_system_prompt'],
                user_instruction=continuation['user_instruction'],
                max_new_tokens=budget-rewritten.generated_tokens,
                timeout_seconds=remaining_time,on_text=on_suffix)))
        return GenerationResult(rewritten.text+separator+suffix.text,
            rewritten.generated_tokens+suffix.generated_tokens,suffix.finish_reason)

    @contextmanager
    def _intervention_context(self, interventions):
        compiled = compile_interventions(self.catalog,self.catalog_model_id,interventions)
        with steering_context(self.decoder_layers,compiled):
            yield

    @contextmanager
    def _layer_steering_context(self, strengths, vector_ids=None):
        if vector_ids:
            if set(vector_ids) - set(strengths):
                raise ValueError('Vector choice has no selected layer strength')
            interventions = []
            for index, strength in strengths.items():
                vector_id = vector_ids.get(index, self.catalog.defaults.get((DEFAULT_MODEL, index)))
                spec = self.catalog.vectors.get(vector_id)
                if spec is None or spec.layer_index != index:
                    raise ValueError('Vector choice must match its layer')
                interventions.append(Intervention(vector_id=vector_id, strength=strength))
            compiled = compile_interventions(self.catalog, DEFAULT_MODEL, interventions)
            with steering_context(self.decoder_layers, compiled):
                yield
            return
        with ExitStack() as stack:
            for index, strength in sorted(strengths.items()):
                if index not in self.layer_vectors:
                    raise ValueError("Unsupported layer or steering strength")
                minimum, maximum = self.layer_bounds[index]
                if not minimum <= strength <= maximum:
                    raise ValueError("Steering strength is outside the catalog bounds")
                if strength:
                    handle = self.decoder_layers[index].register_forward_hook(
                        make_steering_hook(self.layer_vectors[index], strength)
                    )
                    stack.callback(handle.remove)
            yield
