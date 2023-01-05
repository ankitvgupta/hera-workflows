"""The implementation of a Hera workflow for Argo-based workflows"""
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from hera.task import Task

from pydantic import validator

from hera._base_model import BaseModel
from hera.artifact import Artifact
from hera.models import DAGTask as ModelDAGTask
from hera.models import DAGTemplate as ModelDAGTemplate
from hera.models import Inputs as ModelInputs
from hera.models import Outputs as ModelOutputs
from hera.models import PersistentVolumeClaim as ModelPersistentVolumeClaim
from hera.models import Template as ModelTemplate
from hera.models import Volume as ModelVolume
from hera.parameter import Parameter
from hera.validators import validate_name


class DAG:
    """A directed acyclic graph representation (workflow) representation.

    The DAG/workflow is used as a functional representation for a collection of tasks and
    steps. The workflow context controls the overall behaviour of tasks, such as whether to notify completion, whether
    to execute retires, overall parallelism, etc. The workflow can be constructed and submitted to multiple Argo
    endpoints as long as a token can be associated with the endpoint at the given domain.

    Parameters
    ----------
    name: str
        The workflow name. Note that the workflow initiation will replace underscores with dashes.
    inputs: Optional[
            Union[
                List[Union[Parameter, Artifact]],
                List[Union[Parameter, Artifact, Dict[str, Any]]],
                Dict[str, Any],
            ]
    ] = None,
        `Input` or `Parameter` objects that hold parameter inputs. When a dictionary is specified all the key/value
        pairs will be transformed into `Parameter`s. The `key` will be the `name` field of the `Parameter` while the
        `value` will be the `value` field of the `Parameter.
    outputs: Optional[List[Union[Parameter, Artifact]]] = None
        Any outputs to set on the DAG at a global level.
    """

    def __init__(
        self,
        name: str,
        inputs: Optional[
            Union[
                List[Union[Parameter, Artifact]],
                List[Union[Parameter, Artifact, Dict[str, Any]]],
                Dict[str, Any],
            ]
        ] = None,
        outputs: Optional[List[Union[Parameter, Artifact]]] = None,
        tasks: Optional[List[Task]] = None,
    ):
        validate_name(name)
        self.name: str = name
        self.inputs: List[Union[Parameter, Artifact]] = self._parse_inputs(inputs)
        self.outputs: Optional[List[Union[Parameter, Artifact]]] = outputs
        self.tasks: Optional[List[Tasks]] = tasks

    def _parse_inputs(
        self,
        inputs: Optional[
            Union[List[Union[Parameter, Artifact]], List[Union[Parameter, Artifact, Dict[str, Any]]], Dict[str, Any]]
        ],
    ) -> List[Union[Parameter, Artifact]]:
        """Parses the dictionary aspect of the specified inputs and returns a list of parameters and artifacts.

        Parameters
        ----------
        inputs: Union[Dict[str, Any], List[Union[Parameter, Artifact, Dict[str, Any]]]]
            The list of inputs specified on the task. The `Dict` aspect is treated as a mapped collection of
            Parameters. If a single dictionary is specified, all the fields are transformed into `Parameter`s. The key
            is the `name` of the `Parameter` and the `value` is the `value` field of the `Parameter.

        Returns
        -------
        List[Union[Parameter, Artifact]]
            A list of parameters and artifacts. The parameters contain the specified dictionary mapping as well, as
            independent parameters.
        """
        if inputs is None:
            return []

        result: List[Union[Parameter, Artifact]] = []
        if isinstance(inputs, dict):
            for k, v in inputs.items():
                result.append(Parameter(name=k, value=v))
        else:
            for i in inputs:
                if isinstance(i, Parameter) or isinstance(i, Artifact):
                    result.append(i)
                elif isinstance(i, dict):
                    for k, v in i.items():
                        result.append(Parameter(name=k, value=v))
        return result

    def _build_templates(self) -> List[ModelTemplate]:
        """Assembles the templates from sub-DAGs of the DAG"""
        if self.tasks is not None:
            templates = [t for t in [t._build_template() for t in self.tasks] if t]
            sub_templates = [t.dag._build_templates() for t in self.tasks if t.dag]
            sub_templates = [t for sublist in sub_templates for t in sublist]  # flatten
            return templates + sub_templates
        return []

    def _build_dag_tasks(self) -> Optional[List[ModelDAGTask]]:
        """Assembles all the DAG tasks"""
        if self.tasks is not None:
            return [t for t in [t._build_dag_task() for t in self.tasks if not t.is_exit_task] if t]
        return []

    def _build_volume_claim_templates(self) -> List[ModelPersistentVolumeClaim]:
        """Assembles the volume claim templates"""
        # make sure we only have unique names
        vcs = dict()
        for t in self.tasks:
            for v in t._build_volume_claim_templates():
                vcs[v.metadata.name] = v

        # sub-claims:
        sub_volume_claims = [t.dag._build_volume_claim_templates() for t in self.tasks if t.dag]
        for volume_claims in sub_volume_claims:
            for v in volume_claims:
                vcs[v.metadata.name] = v
        return list(vcs.values())

    def _build_persistent_volume_claims(self) -> List[ModelVolume]:
        """Assembles the persistent volume claim templates"""
        # Make sure we only have unique names
        pvcs = dict()
        for t in self.tasks:
            for v in t._build_persistent_volume_claims():
                pvcs[v.name] = v

        # sub-claims:
        sub_volume_claims = [t.dag._build_persistent_volume_claims() for t in self.tasks if t.dag]
        for volume_claims in sub_volume_claims:
            for v in volume_claims:
                pvcs[v.name] = v

        return list(pvcs.values())

    def build(self) -> List[ModelTemplate]:
        """Assembles the main DAG/workflow template"""
        dag = ModelTemplate(
            name=self.name,
            inputs=ModelInputs(
                parameters=[obj for obj in self.inputs if isinstance(obj, Parameter)],
                artifacts=[obj for obj in self.inputs if isinstance(obj, Artifact)],
            ),
            outputs=ModelOutputs(
                parameters=[obj for obj in self.outputs if isinstance(obj, Parameter)],
                artifacts=[obj for obj in self.outputs if isinstance(obj, Artifact)],
            ),
            dag=ModelDAGTemplate(tasks=self._build_dag_tasks()),
        )

        # Assemble the sub-dags if present in task templates
        sub_dags = [t.dag.build() for t in self.tasks if t.dag]
        sub_dags = [item for sublist in sub_dags for item in sublist]  # flatten
        return [dag] + sub_dags

    def __enter__(self) -> "DAG":
        """Enter the context of the DAG. This supports the use of `with DAG(...)`"""
        from hera import dag_context

        self.in_context = True
        dag_context.enter(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context of the DAG. This supports the use of `with DAG(...)`"""
        from hera import dag_context

        self.in_context = False
        dag_context.exit()

    def add_task(self, t: "Task") -> "DAG":
        """Add a task to the DAG. Note that tasks are added automatically when the DAG context is used"""
        self.tasks.append(t)
        return self

    def add_tasks(self, *ts: "Task") -> "DAG":
        """Add a collection of tasks to the DAG.

        Note that tasks are added automatically when the DAG context is used
        """
        self.tasks.extend(ts)
        return self

    def get_parameter(self, name: str) -> Parameter:
        """Returns a DAG output as a `Parameter` to use an input somewhere else"""
        if next((p for p in self.outputs if p.name == name), None) is None:
            raise KeyError(f"Could not assemble a parameter as `{name}` is not a DAG output")
        return Parameter(name, value=f"{{{{inputs.parameters.{name}}}}}")
